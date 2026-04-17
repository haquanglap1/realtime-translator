"""
LLM configuration dialog.

Supports:
  - provider presets
  - remote model listing via OpenAI-compatible /models
  - fallback validation for APIs that do not support /models
  - safe save flow so an invalid remote model is not persisted silently
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QTextEdit, QSpinBox,
    QScrollArea, QWidget, QFileDialog
)

from utils.config import LLMConfig, save_config_section


PROVIDERS = {
    "Ollama": {
        "base_url": "http://localhost:11434/v1",
        "api_key": "ollama",
        "models": ["qwen2.5:7b", "qwen2.5:14b", "llama3.1:8b", "gemma2:9b", "phi3:medium", "mistral:7b"],
    },
    "LM Studio": {
        "base_url": "http://localhost:1234/v1",
        "api_key": "lm-studio",
        "models": [],
    },
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1-nano"],
    },
    "DeepSeek": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "Groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": "",
        "models": ["llama-3.1-8b-instant", "llama-3.3-70b-versatile", "gemma2-9b-it"],
    },
    "SiliconCloud": {
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key": "",
        "models": ["Qwen/Qwen2.5-7B-Instruct", "deepseek-ai/DeepSeek-V3"],
    },
    "Custom": {
        "base_url": "",
        "api_key": "",
        "models": [],
    },
}

_PROVIDER_MAP = {
    "ollama": "Ollama",
    "openai": "OpenAI",
    "lm-studio": "LM Studio",
    "deepseek": "DeepSeek",
    "groq": "Groq",
    "siliconcloud": "SiliconCloud",
    "custom": "Custom",
}

_PROVIDER_MAP_REVERSE = {v: k for k, v in _PROVIDER_MAP.items()}

DIALOG_STYLE = """
QDialog {
    background-color: #1a1a1a;
    color: #ffffff;
}
QLabel {
    color: #cccccc;
    font-size: 12px;
}
QLineEdit {
    background-color: #2a2a2a;
    color: #ffffff;
    border: 1px solid #444444;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
}
QLineEdit:focus {
    border-color: #4CAF50;
}
QLineEdit:disabled {
    background-color: #1e1e1e;
    color: #666666;
}
QComboBox {
    background-color: #2a2a2a;
    color: #ffffff;
    border: 1px solid #444444;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    min-width: 200px;
}
QComboBox:focus {
    border-color: #4CAF50;
}
QComboBox::drop-down {
    border: none;
    width: 30px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #aaaaaa;
    margin-right: 10px;
}
QComboBox QAbstractItemView {
    background-color: #2a2a2a;
    color: #ffffff;
    border: 1px solid #444444;
    selection-background-color: #3a3a3a;
}
QPushButton {
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 12px;
    font-weight: bold;
}
QPushButton:disabled {
    background-color: #333333;
    color: #666666;
}
"""

TARGET_LANGUAGES = [
    "Vietnamese",
    "English",
    "Chinese",
    "Japanese",
    "Korean",
    "French",
    "Spanish",
    "German",
    "Russian",
    "Thai",
    "Indonesian",
]


def _merge_model_names(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for model in group:
            if not model or model in seen:
                continue
            seen.add(model)
            merged.append(model)
    return merged


class _ConnectionTestThread(QThread):
    """Fetch models from the API if possible, or validate the current model."""

    finished = pyqtSignal(bool, object, str)

    def __init__(self, base_url: str, api_key: str, model: str):
        super().__init__()
        self._base_url = base_url
        self._api_key = api_key
        self._model = model

    def run(self):
        client = None
        try:
            from openai import OpenAI

            client = OpenAI(base_url=self._base_url, api_key=self._api_key)

            try:
                response = client.models.list()
                model_ids = sorted(
                    item.id for item in response.data if getattr(item, "id", None)
                )
                if model_ids:
                    self.finished.emit(
                        True,
                        model_ids,
                        f"Ket noi thanh cong. Tim thay {len(model_ids)} model."
                    )
                else:
                    self.finished.emit(
                        True,
                        [],
                        "Ket noi thanh cong nhung API khong tra ve model nao."
                    )
                return
            except Exception as list_error:
                if not self._model:
                    self.finished.emit(
                        False,
                        [],
                        f"Khong list duoc model tu API: {str(list_error)[:180]}"
                    )
                    return

                client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": "Hi"}],
                    max_tokens=5,
                )
                self.finished.emit(
                    True,
                    [self._model],
                    "Ket noi thanh cong. API nay khong ho tro /models, giu model hien tai."
                )
        except Exception as e:
            self.finished.emit(False, [], f"Loi ket noi: {str(e)[:200]}")
        finally:
            if client is not None:
                client.close()


class LLMConfigDialog(QDialog):
    """Dialog for configuring LLM translation settings."""

    def __init__(self, config: LLMConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._test_thread: Optional[_ConnectionTestThread] = None
        self._remote_models: list[str] = []
        self._suspend_provider_change = False

        self.setWindowTitle("LLM Configuration")
        self.setMinimumSize(520, 480)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint
        )

        self._build_ui()
        self._load_from_config()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        
        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        title = QLabel("LLM Configuration")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)

        subtitle = QLabel("Cau hinh dich vu LLM de dich thuat real-time")
        subtitle.setStyleSheet("font-size: 11px; color: #888888;")
        layout.addWidget(subtitle)

        layout.addSpacing(4)

        layout.addWidget(self._section_label("LLM Provider"))
        self._provider_combo = QComboBox()
        self._provider_combo.addItems(list(PROVIDERS.keys()))
        self._provider_combo.currentTextChanged.connect(self._on_provider_changed)
        layout.addWidget(self._provider_combo)

        layout.addWidget(self._section_label("API Key"))
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setPlaceholderText("Nhap API key...")
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        key_layout = QHBoxLayout()
        key_layout.setSpacing(8)
        key_layout.addWidget(self._api_key_edit)
        self._toggle_key_btn = QPushButton("Show")
        self._toggle_key_btn.setFixedSize(50, 34)
        self._toggle_key_btn.setStyleSheet("""
            QPushButton { background-color: #333333; color: #cccccc; }
            QPushButton:hover { background-color: #444444; }
        """)
        self._toggle_key_btn.clicked.connect(self._toggle_key_visibility)
        key_layout.addWidget(self._toggle_key_btn)
        layout.addLayout(key_layout)

        layout.addWidget(self._section_label("Base URL"))
        self._base_url_edit = QLineEdit()
        self._base_url_edit.setPlaceholderText("https://api.openai.com/v1")
        layout.addWidget(self._base_url_edit)

        layout.addWidget(self._section_label("Model"))
        model_layout = QHBoxLayout()
        model_layout.setSpacing(8)
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.lineEdit().setPlaceholderText("Nhap hoac chon model...")
        model_layout.addWidget(self._model_combo)
        self._refresh_models_btn = QPushButton("Refresh")
        self._refresh_models_btn.setFixedWidth(90)
        self._refresh_models_btn.setStyleSheet("""
            QPushButton { background-color: #333333; color: #cccccc; }
            QPushButton:hover { background-color: #444444; }
        """)
        self._refresh_models_btn.clicked.connect(lambda: self._refresh_models(manual=True))
        model_layout.addWidget(self._refresh_models_btn)
        layout.addLayout(model_layout)

        layout.addWidget(self._section_label("Ngon ngu dich"))
        self._language_combo = QComboBox()
        self._language_combo.addItems(TARGET_LANGUAGES)
        self._language_combo.setEditable(True)
        layout.addWidget(self._language_combo)

        layout.addWidget(self._section_label("Custom System Prompt"))
        self._prompt_edit = QTextEdit()
        self._prompt_edit.setPlaceholderText("Lenh dieu huong AI (VD: Keep technical terms in English, do not translate them...)")
        self._prompt_edit.setMaximumHeight(80)
        self._prompt_edit.setStyleSheet("""
            QTextEdit {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
            }
            QTextEdit:focus { border-color: #4CAF50; }
        """)
        layout.addWidget(self._prompt_edit)

        # ── Manuscript Matching (Rewrite) ─────────────────────────
        rewrite_title = QLabel("Van ban doi chieu (Rewrite)")
        rewrite_title.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #FFE082; margin-top: 8px;"
        )
        layout.addWidget(rewrite_title)

        rewrite_desc = QLabel(
            "Cac truong nay chi ap dung khi an nut Rewrite, giup ban dich chinh xac hon."
        )
        rewrite_desc.setStyleSheet("font-size: 11px; color: #888888;")
        layout.addWidget(rewrite_desc)

        layout.addWidget(self._section_label(
            "Bang thuat ngu (VD: Machine Learning -> Hoc may)"
        ))
        self._glossary_edit = QTextEdit()
        self._glossary_edit.setPlaceholderText(
            "Moi dong mot cap, VD:\n"
            "Machine Learning -> Hoc may\n"
            "Elon Musk -> Elon Musk\n"
            "call -> cuoc goi\n"
            "Turing -> Turing"
        )
        self._glossary_edit.setMaximumHeight(90)
        self._glossary_edit.setStyleSheet("""
            QTextEdit {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
            }
            QTextEdit:focus { border-color: #FFE082; }
        """)
        layout.addWidget(self._glossary_edit)

        layout.addWidget(self._section_label(
            "Van ban goc / ban thao (transcript, bai giang, ...)"
        ))
        self._reference_edit = QTextEdit()
        self._reference_edit.setPlaceholderText(
            "Dan noi dung van ban goc de LLM doi chieu khi rewrite,\n"
            "giup sua loi phien am va dich chinh xac hon..."
        )
        self._reference_edit.setMaximumHeight(100)
        self._reference_edit.setStyleSheet("""
            QTextEdit {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
            }
            QTextEdit:focus { border-color: #FFE082; }
        """)
        layout.addWidget(self._reference_edit)

        layout.addWidget(self._section_label(
            "Yeu cau chinh sua (VD: Thong nhat dai tu nhan xung, ...)"
        ))
        self._correction_edit = QTextEdit()
        self._correction_edit.setPlaceholderText(
            "VD:\n"
            "- Thong nhat dai tu nhan xung ngo thu nhat\n"
            "- Chuan hoa thuat ngu chuyen nganh\n"
            "- Giu nguyen ten rieng tieng Anh"
        )
        self._correction_edit.setMaximumHeight(80)
        self._correction_edit.setStyleSheet("""
            QTextEdit {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
            }
            QTextEdit:focus { border-color: #FFE082; }
        """)
        layout.addWidget(self._correction_edit)

        config_layout = QHBoxLayout()
        
        batch_layout = QVBoxLayout()
        batch_layout.addWidget(self._section_label("Batch Size"))
        self._batch_spin = QSpinBox()
        self._batch_spin.setRange(1, 100)
        self._batch_spin.setStyleSheet("background-color: #2a2a2a; color: #ffffff; border: 1px solid #444444; border-radius: 4px; padding: 5px;")
        batch_layout.addWidget(self._batch_spin)
        config_layout.addLayout(batch_layout)

        thread_layout = QVBoxLayout()
        thread_layout.addWidget(self._section_label("Thread Count"))
        self._thread_spin = QSpinBox()
        self._thread_spin.setRange(1, 50)
        self._thread_spin.setStyleSheet("background-color: #2a2a2a; color: #ffffff; border: 1px solid #444444; border-radius: 4px; padding: 5px;")
        thread_layout.addWidget(self._thread_spin)
        config_layout.addLayout(thread_layout)

        layout.addLayout(config_layout)

        layout.addWidget(self._section_label("Thu muc luu loi thoai (khi an Stop)"))
        save_layout = QHBoxLayout()
        self._save_dir_edit = QLineEdit()
        self._save_dir_edit.setPlaceholderText("De trong neu khong muon tu dong luu...")
        save_layout.addWidget(self._save_dir_edit)
        
        btn_browse = QPushButton("Browse...")
        btn_browse.setStyleSheet("""
            QPushButton { background-color: #333333; color: #cccccc; padding: 6px 12px; }
            QPushButton:hover { background-color: #444444; }
        """)
        btn_browse.clicked.connect(self._browse_save_dir)
        save_layout.addWidget(btn_browse)
        layout.addLayout(save_layout)

        self._enabled_layout = QHBoxLayout()
        self._enabled_label = QLabel("Bat dich thuat LLM")
        self._enabled_label.setStyleSheet("color: #cccccc; font-size: 12px;")
        self._enabled_layout.addWidget(self._enabled_label)
        self._enabled_layout.addStretch()
        self._enabled_btn = QPushButton("ON")
        self._enabled_btn.setFixedSize(60, 28)
        self._enabled_btn.clicked.connect(self._toggle_enabled)
        self._enabled_layout.addWidget(self._enabled_btn)
        layout.addLayout(self._enabled_layout)

        layout.addStretch()

        footer = QHBoxLayout()
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("font-size: 11px; color: #888888;")
        footer.addWidget(self._status_label)
        footer.addStretch()

        self._check_btn = QPushButton("Check Connection")
        self._check_btn.setStyleSheet("""
            QPushButton { background-color: #1565C0; color: white; }
            QPushButton:hover { background-color: #1976D2; }
        """)
        self._check_btn.clicked.connect(lambda: self._refresh_models(manual=True))
        footer.addWidget(self._check_btn)

        save_btn = QPushButton("Luu")
        save_btn.setStyleSheet("""
            QPushButton { background-color: #388e3c; color: white; }
            QPushButton:hover { background-color: #4caf50; }
        """)
        save_btn.clicked.connect(self._save_and_close)
        footer.addWidget(save_btn)

        cancel_btn = QPushButton("Huy")
        cancel_btn.setStyleSheet("""
            QPushButton { background-color: #555555; color: white; }
            QPushButton:hover { background-color: #666666; }
        """)
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn)

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        footer_container = QWidget()
        footer_container.setLayout(footer)
        footer_container.setStyleSheet("background-color: #1a1a1a; border-top: 1px solid #333333;")
        main_layout.addWidget(footer_container)

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("color: #aaaaaa; font-size: 11px; font-weight: bold;")
        return label

    def _load_from_config(self) -> None:
        cfg = self._config

        self._suspend_provider_change = True
        display_name = _PROVIDER_MAP.get(cfg.provider, "Custom")
        idx = self._provider_combo.findText(display_name)
        if idx >= 0:
            self._provider_combo.setCurrentIndex(idx)
        else:
            self._provider_combo.setCurrentText("Custom")
        self._suspend_provider_change = False

        self._api_key_edit.setText(cfg.api_key)
        self._base_url_edit.setText(cfg.base_url)

        self._update_model_list(display_name)
        self._model_combo.setCurrentText(cfg.model)

        idx = self._language_combo.findText(cfg.target_language)
        if idx >= 0:
            self._language_combo.setCurrentIndex(idx)
        else:
            self._language_combo.setCurrentText(cfg.target_language)

        self._prompt_edit.setPlainText(cfg.custom_prompt)
        self._glossary_edit.setPlainText(getattr(cfg, 'glossary', ''))
        self._reference_edit.setPlainText(getattr(cfg, 'reference_text', ''))
        self._correction_edit.setPlainText(getattr(cfg, 'correction_instructions', ''))
        self._batch_spin.setValue(cfg.batch_size)
        self._thread_spin.setValue(cfg.thread_count)
        self._save_dir_edit.setText(getattr(cfg, 'transcript_save_dir', ''))

        self._update_enabled_ui(cfg.enabled)

        if cfg.base_url and (cfg.api_key or display_name in {"Ollama", "LM Studio"}):
            QTimer.singleShot(0, lambda: self._refresh_models(manual=False))

    def _save_and_close(self) -> None:
        provider_display = self._provider_combo.currentText()
        model_name = self._model_combo.currentText().strip()

        self._config.provider = _PROVIDER_MAP_REVERSE.get(provider_display, "custom")
        self._config.api_key = self._api_key_edit.text().strip()
        self._config.base_url = self._base_url_edit.text().strip()
        self._config.model = model_name
        self._config.target_language = self._language_combo.currentText().strip()
        self._config.custom_prompt = self._prompt_edit.toPlainText().strip()
        self._config.glossary = self._glossary_edit.toPlainText().strip()
        self._config.reference_text = self._reference_edit.toPlainText().strip()
        self._config.correction_instructions = self._correction_edit.toPlainText().strip()
        self._config.batch_size = self._batch_spin.value()
        self._config.thread_count = self._thread_spin.value()
        self._config.transcript_save_dir = self._save_dir_edit.text().strip()

        if not self._config.base_url:
            QMessageBox.warning(self, "Loi", "Base URL khong duoc de trong.")
            return
        if not model_name:
            QMessageBox.warning(self, "Loi", "Model khong duoc de trong.")
            return
        if self._remote_models and model_name not in set(self._remote_models):
            QMessageBox.warning(
                self,
                "Loi",
                "Model khong nam trong danh sach API tra ve. Bam Refresh de lay lai model dung.",
            )
            return

        save_config_section("llm", {
            "enabled": self._config.enabled,
            "provider": self._config.provider,
            "base_url": self._config.base_url,
            "api_key": self._config.api_key,
            "model": self._config.model,
            "target_language": self._config.target_language,
            "context_segments": self._config.context_segments,
            "temperature": self._config.temperature,
            "custom_prompt": self._config.custom_prompt,
            "glossary": self._config.glossary,
            "reference_text": self._config.reference_text,
            "correction_instructions": self._config.correction_instructions,
            "batch_size": self._config.batch_size,
            "thread_count": self._config.thread_count,
            "transcript_save_dir": self._config.transcript_save_dir,
        })

        self.accept()

    def _browse_save_dir(self) -> None:
        current_dir = self._save_dir_edit.text().strip()
        dir_path = QFileDialog.getExistingDirectory(
            self, "Chon thu muc luu file txt", current_dir
        )
        if dir_path:
            self._save_dir_edit.setText(dir_path)

    def _on_provider_changed(self, provider_name: str) -> None:
        if self._suspend_provider_change:
            return

        preset = PROVIDERS.get(provider_name)
        if not preset:
            return

        current_key = self._api_key_edit.text().strip()
        self._base_url_edit.setText(preset["base_url"])

        if preset["api_key"]:
            self._api_key_edit.setText(preset["api_key"])
        elif not current_key:
            self._api_key_edit.clear()

        self._remote_models = []
        self._update_model_list(provider_name)
        self._status_label.setText("")

        if self._base_url_edit.text().strip() and (self._api_key_edit.text().strip() or provider_name in {"Ollama", "LM Studio"}):
            QTimer.singleShot(0, lambda: self._refresh_models(manual=False))

    def _update_model_list(self, provider_name: str) -> None:
        preset = PROVIDERS.get(provider_name, {})
        preset_models = preset.get("models", [])
        current = self._model_combo.currentText().strip()
        merged_models = _merge_model_names(preset_models, self._remote_models)

        self._model_combo.clear()
        if merged_models:
            self._model_combo.addItems(merged_models)
        if current:
            self._model_combo.setCurrentText(current)

    def _toggle_enabled(self) -> None:
        self._config.enabled = not self._config.enabled
        self._update_enabled_ui(self._config.enabled)

    def _update_enabled_ui(self, enabled: bool) -> None:
        if enabled:
            self._enabled_btn.setText("ON")
            self._enabled_btn.setStyleSheet("""
                QPushButton { background-color: #388e3c; color: white; border-radius: 6px; }
                QPushButton:hover { background-color: #4caf50; }
            """)
        else:
            self._enabled_btn.setText("OFF")
            self._enabled_btn.setStyleSheet("""
                QPushButton { background-color: #555555; color: #999999; border-radius: 6px; }
                QPushButton:hover { background-color: #666666; }
            """)

    def _toggle_key_visibility(self) -> None:
        if self._api_key_edit.echoMode() == QLineEdit.EchoMode.Password:
            self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._toggle_key_btn.setText("Hide")
        else:
            self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._toggle_key_btn.setText("Show")

    def _refresh_models(self, manual: bool) -> None:
        base_url = self._base_url_edit.text().strip()
        api_key = self._api_key_edit.text().strip()
        model = self._model_combo.currentText().strip()

        if not base_url:
            self._status_label.setText("Base URL trong!")
            self._status_label.setStyleSheet("font-size: 11px; color: #f44336;")
            return

        if self._test_thread is not None:
            if manual:
                self._status_label.setText("Dang lay danh sach model...")
            return

        self._check_btn.setEnabled(False)
        self._refresh_models_btn.setEnabled(False)
        self._check_btn.setText("Dang kiem tra...")
        self._status_label.setText("Dang lay danh sach model...")
        self._status_label.setStyleSheet("font-size: 11px; color: #888888;")

        self._test_thread = _ConnectionTestThread(base_url, api_key, model)
        self._test_thread.finished.connect(self._on_connection_result)
        self._test_thread.start()

    def _on_connection_result(self, success: bool, models: object, message: str) -> None:
        self._check_btn.setEnabled(True)
        self._refresh_models_btn.setEnabled(True)
        self._check_btn.setText("Check Connection")

        if success:
            fetched_models = [m for m in models if isinstance(m, str)] if isinstance(models, list) else []
            if fetched_models:
                self._remote_models = fetched_models
                current = self._model_combo.currentText().strip()
                self._update_model_list(self._provider_combo.currentText())
                if current and current not in set(fetched_models):
                    self._model_combo.setCurrentText(fetched_models[0])
            self._status_label.setStyleSheet("font-size: 11px; color: #4caf50;")
        else:
            self._status_label.setStyleSheet("font-size: 11px; color: #f44336;")

        self._status_label.setText(message)
        self._test_thread = None
