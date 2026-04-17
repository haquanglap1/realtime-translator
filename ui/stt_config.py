"""
STT and speaker labeling configuration dialog.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from utils.config import AppConfig, save_config_section
from utils.model_manager import WHISPER_MODELS, is_model_downloaded


DIALOG_STYLE = """
QDialog {
    background-color: #1a1a1a;
    color: #ffffff;
}
QLabel {
    color: #cccccc;
    font-size: 12px;
}
QComboBox {
    background-color: #2a2a2a;
    color: #ffffff;
    border: 1px solid #444444;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    min-width: 240px;
}
QComboBox:focus {
    border-color: #4CAF50;
}
QComboBox QAbstractItemView {
    background-color: #2a2a2a;
    color: #ffffff;
    border: 1px solid #444444;
    selection-background-color: #3a3a3a;
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
QPushButton {
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 12px;
    font-weight: bold;
}
"""

SOURCE_OPTIONS = [
    ("Microphone", "mic"),
    ("System audio", "loopback"),
    ("Mic + System", "both"),
]

SPEAKER_STRATEGY_OPTIONS = [
    ("By audio source", "source"),
    ("By detected language", "language"),
    ("Pyannote diarization", "pyannote"),
]

DEVICE_OPTIONS = [
    ("GPU (CUDA)", "cuda"),
    ("CPU", "cpu"),
]

ENGINE_OPTIONS = [
    ("Faster Whisper (local)", "faster-whisper"),
    ("OpenAI Whisper API", "openai-api"),
]

STT_API_PRESETS = {
    "OpenAI": {
        "api_base": "https://api.openai.com/v1",
        "api_model": "whisper-1",
    },
    "Groq": {
        "api_base": "https://api.groq.com/openai/v1",
        "api_model": "whisper-large-v3",
    },
    "Custom": {
        "api_base": "",
        "api_model": "",
    },
}


class STTConfigDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config

        self.setWindowTitle("STT Configuration")
        self.setMinimumSize(580, 720)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint
        )

        self._build_ui()
        self._load_from_config()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background-color: transparent; }"
            "QScrollBar:vertical { width: 8px; background: transparent; }"
            "QScrollBar::handle:vertical {"
            " background: rgba(255,255,255,60); border-radius: 4px; }"
        )

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        scroll.setWidget(body)
        outer.addWidget(scroll)

        title = QLabel("STT Configuration")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)

        subtitle = QLabel("Chon nguon am thanh, STT engine va cach gan speaker")
        subtitle.setStyleSheet("font-size: 11px; color: #888888;")
        layout.addWidget(subtitle)

        layout.addWidget(self._section_label("Audio source"))
        self._source_combo = QComboBox()
        for label, value in SOURCE_OPTIONS:
            self._source_combo.addItem(label, value)
        self._source_combo.currentIndexChanged.connect(self._sync_engine_state)
        layout.addWidget(self._source_combo)

        layout.addWidget(self._section_label("Speaker labeling"))
        self._speaker_strategy_combo = QComboBox()
        for label, value in SPEAKER_STRATEGY_OPTIONS:
            self._speaker_strategy_combo.addItem(label, value)
        self._speaker_strategy_combo.currentIndexChanged.connect(self._sync_engine_state)
        layout.addWidget(self._speaker_strategy_combo)

        self._diarization_section = QWidget()
        diarization_layout = QVBoxLayout(self._diarization_section)
        diarization_layout.setContentsMargins(0, 0, 0, 0)
        diarization_layout.setSpacing(10)

        diarization_layout.addWidget(self._section_label("Hugging Face Token"))
        self._hf_token_edit = QLineEdit()
        self._hf_token_edit.setPlaceholderText(
            "hf_... (required for pyannote/speaker-diarization-community-1)"
        )
        self._hf_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        hf_layout = QHBoxLayout()
        hf_layout.setSpacing(8)
        hf_layout.addWidget(self._hf_token_edit)
        self._toggle_hf_btn = QPushButton("Show")
        self._toggle_hf_btn.setFixedSize(50, 34)
        self._toggle_hf_btn.setStyleSheet(
            """
            QPushButton { background-color: #333333; color: #cccccc; }
            QPushButton:hover { background-color: #444444; }
            """
        )
        self._toggle_hf_btn.clicked.connect(self._toggle_hf_visibility)
        hf_layout.addWidget(self._toggle_hf_btn)
        diarization_layout.addLayout(hf_layout)

        speaker_count_layout = QHBoxLayout()
        speaker_count_layout.setSpacing(12)

        exact_layout = QVBoxLayout()
        exact_layout.addWidget(self._section_label("Exact speakers (0 = auto)"))
        self._num_speakers_spin = self._spin_box(0, 8)
        exact_layout.addWidget(self._num_speakers_spin)
        speaker_count_layout.addLayout(exact_layout)

        max_layout = QVBoxLayout()
        max_layout.addWidget(self._section_label("Max speakers"))
        self._max_speakers_spin = self._spin_box(2, 16)
        max_layout.addWidget(self._max_speakers_spin)
        speaker_count_layout.addLayout(max_layout)

        diarization_layout.addLayout(speaker_count_layout)
        layout.addWidget(self._diarization_section)

        layout.addWidget(self._section_label("STT engine"))
        self._engine_combo = QComboBox()
        for label, value in ENGINE_OPTIONS:
            self._engine_combo.addItem(label, value)
        self._engine_combo.currentIndexChanged.connect(self._sync_engine_state)
        layout.addWidget(self._engine_combo)

        self._local_section = QWidget()
        local_layout = QVBoxLayout(self._local_section)
        local_layout.setContentsMargins(0, 0, 0, 0)
        local_layout.setSpacing(10)

        local_layout.addWidget(self._section_label("Whisper model (local)"))
        self._model_combo = QComboBox()
        for model_name in WHISPER_MODELS:
            downloaded = "yes" if is_model_downloaded(model_name) else "no"
            self._model_combo.addItem(f"{model_name} ({downloaded})", model_name)
        self._model_combo.currentIndexChanged.connect(self._sync_engine_state)
        local_layout.addWidget(self._model_combo)

        local_layout.addWidget(self._section_label("Inference device"))
        self._device_combo = QComboBox()
        for label, value in DEVICE_OPTIONS:
            self._device_combo.addItem(label, value)
        local_layout.addWidget(self._device_combo)
        layout.addWidget(self._local_section)

        self._api_section = QWidget()
        api_layout = QVBoxLayout(self._api_section)
        api_layout.setContentsMargins(0, 0, 0, 0)
        api_layout.setSpacing(10)

        api_layout.addWidget(self._section_label("STT Provider"))
        self._stt_provider_combo = QComboBox()
        self._stt_provider_combo.addItems(list(STT_API_PRESETS.keys()))
        self._stt_provider_combo.currentTextChanged.connect(self._on_stt_provider_changed)
        api_layout.addWidget(self._stt_provider_combo)

        api_layout.addWidget(self._section_label("Base URL"))
        self._api_base_edit = QLineEdit()
        self._api_base_edit.setPlaceholderText("https://api.openai.com/v1")
        api_layout.addWidget(self._api_base_edit)

        api_layout.addWidget(self._section_label("API Key"))
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setPlaceholderText("Nhap API key...")
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        key_layout = QHBoxLayout()
        key_layout.setSpacing(8)
        key_layout.addWidget(self._api_key_edit)
        self._toggle_key_btn = QPushButton("Show")
        self._toggle_key_btn.setFixedSize(50, 34)
        self._toggle_key_btn.setStyleSheet(
            """
            QPushButton { background-color: #333333; color: #cccccc; }
            QPushButton:hover { background-color: #444444; }
            """
        )
        self._toggle_key_btn.clicked.connect(self._toggle_key_visibility)
        key_layout.addWidget(self._toggle_key_btn)
        api_layout.addLayout(key_layout)

        api_layout.addWidget(self._section_label("Model"))
        self._api_model_edit = QLineEdit()
        self._api_model_edit.setPlaceholderText("whisper-1")
        api_layout.addWidget(self._api_model_edit)
        layout.addWidget(self._api_section)

        # ── Section: Chong hallucination / VAD tuning ──────────────────
        layout.addWidget(self._build_vad_section())

        self._hint_label = QLabel("")
        self._hint_label.setStyleSheet("font-size: 11px; color: #aaaaaa;")
        self._hint_label.setWordWrap(True)
        layout.addWidget(self._hint_label)

        layout.addStretch()

        footer_bar = QWidget()
        footer_bar.setStyleSheet("background-color: #1a1a1a;")
        footer = QHBoxLayout(footer_bar)
        footer.setContentsMargins(20, 10, 20, 14)
        footer.addStretch()

        save_btn = QPushButton("Luu")
        save_btn.setStyleSheet(
            """
            QPushButton { background-color: #388e3c; color: white; }
            QPushButton:hover { background-color: #4caf50; }
            """
        )
        save_btn.clicked.connect(self._save_and_close)
        footer.addWidget(save_btn)

        cancel_btn = QPushButton("Huy")
        cancel_btn.setStyleSheet(
            """
            QPushButton { background-color: #555555; color: white; }
            QPushButton:hover { background-color: #666666; }
            """
        )
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn)

        outer.addWidget(footer_bar)

    def _build_vad_section(self) -> QWidget:
        """Section 'Chong hallucination & VAD' — gom VAD + Whisper thresholds."""
        container = QWidget()
        container.setStyleSheet(
            "background-color: #1f1f1f; border-radius: 8px;"
        )
        box = QVBoxLayout(container)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(8)

        header = QLabel("Chong hallucination & VAD tuning")
        header.setStyleSheet(
            "color: #ffca28; font-size: 13px; font-weight: bold;"
        )
        box.addWidget(header)

        desc = QLabel(
            "Thieu lop loc -> Whisper hay 'bia' khi noi o moi truong on. "
            "Tang cac nguong neu con thay hallucination; giam neu bo lo speech that."
        )
        desc.setStyleSheet("color: #bbbbbb; font-size: 11px;")
        desc.setWordWrap(True)
        box.addWidget(desc)

        # Hang 1: speech_threshold + min_segment_duration_ms
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        col_a = QVBoxLayout()
        col_a.addWidget(self._section_label("Energy threshold (0.005–0.15)"))
        self._speech_threshold_spin = self._double_spin(0.005, 0.15, 0.005, 3)
        col_a.addWidget(self._speech_threshold_spin)
        row1.addLayout(col_a)

        col_b = QVBoxLayout()
        col_b.addWidget(self._section_label("Min duration (ms)"))
        self._min_duration_spin = self._spin_box(100, 3000)
        self._min_duration_spin.setSingleStep(50)
        col_b.addWidget(self._min_duration_spin)
        row1.addLayout(col_b)
        box.addLayout(row1)

        # Hang 2: min_segment_rms + min_active_ratio
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        col_c = QVBoxLayout()
        col_c.addWidget(self._section_label("Min segment RMS (0.0–0.1)"))
        self._min_rms_spin = self._double_spin(0.0, 0.1, 0.005, 3)
        col_c.addWidget(self._min_rms_spin)
        row2.addLayout(col_c)

        col_d = QVBoxLayout()
        col_d.addWidget(self._section_label("Min active-frame ratio (0.0–1.0)"))
        self._min_active_ratio_spin = self._double_spin(0.0, 1.0, 0.05, 2)
        col_d.addWidget(self._min_active_ratio_spin)
        row2.addLayout(col_d)
        box.addLayout(row2)

        # Hang 3: min_speech_frames (frame 30ms nen x30ms = duration floor)
        row3 = QHBoxLayout()
        row3.setSpacing(10)
        col_e = QVBoxLayout()
        col_e.addWidget(self._section_label("Min speech frames (~30ms/frame)"))
        self._min_speech_frames_spin = self._spin_box(1, 100)
        col_e.addWidget(self._min_speech_frames_spin)
        row3.addLayout(col_e)
        box.addLayout(row3)

        # Silero VAD toggle + threshold
        self._silero_checkbox = QCheckBox(
            "Bat Silero VAD (deep-learning VAD, can: pip install silero-vad)"
        )
        self._silero_checkbox.setStyleSheet(
            "color: #ffffff; font-size: 12px; padding: 4px 0;"
        )
        box.addWidget(self._silero_checkbox)

        silero_row = QHBoxLayout()
        silero_row.addWidget(self._section_label("Silero speech prob threshold (0.0–1.0)"))
        self._silero_prob_spin = self._double_spin(0.0, 1.0, 0.05, 2)
        silero_row.addWidget(self._silero_prob_spin)
        box.addLayout(silero_row)

        # Whisper thresholds (chỉ áp dụng cho faster-whisper local)
        whisper_label = QLabel("— Whisper local thresholds (chi faster-whisper) —")
        whisper_label.setStyleSheet("color: #888888; font-size: 10px; padding-top: 6px;")
        box.addWidget(whisper_label)

        wrow = QHBoxLayout()
        wrow.setSpacing(10)
        col_f = QVBoxLayout()
        col_f.addWidget(self._section_label("no_speech_threshold"))
        self._no_speech_spin = self._double_spin(0.0, 1.0, 0.05, 2)
        col_f.addWidget(self._no_speech_spin)
        wrow.addLayout(col_f)

        col_g = QVBoxLayout()
        col_g.addWidget(self._section_label("log_prob_threshold"))
        self._log_prob_spin = self._double_spin(-3.0, 0.0, 0.1, 2)
        col_g.addWidget(self._log_prob_spin)
        wrow.addLayout(col_g)

        col_h = QVBoxLayout()
        col_h.addWidget(self._section_label("compression_ratio_threshold"))
        self._comp_ratio_spin = self._double_spin(1.0, 5.0, 0.1, 2)
        col_h.addWidget(self._comp_ratio_spin)
        wrow.addLayout(col_h)
        box.addLayout(wrow)

        self._vad_filter_checkbox = QCheckBox(
            "Bat vad_filter cua faster-whisper (Silero noi bo, chi local)"
        )
        self._vad_filter_checkbox.setStyleSheet(
            "color: #ffffff; font-size: 12px; padding: 4px 0;"
        )
        box.addWidget(self._vad_filter_checkbox)

        return container

    def _double_spin(
        self, low: float, high: float, step: float, decimals: int,
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        spin.setStyleSheet(
            "background-color: #2a2a2a; color: #ffffff;"
            " border: 1px solid #444444; border-radius: 4px; padding: 5px;"
        )
        return spin

    def _spin_box(self, low: int, high: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setStyleSheet(
            "background-color: #2a2a2a; color: #ffffff; border: 1px solid #444444; border-radius: 4px; padding: 5px;"
        )
        return spin

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("color: #aaaaaa; font-size: 11px; font-weight: bold;")
        return label

    def _load_from_config(self) -> None:
        self._set_combo_value(self._source_combo, self._config.audio.source)
        self._set_combo_value(
            self._speaker_strategy_combo,
            self._config.audio.speaker_strategy,
        )
        self._hf_token_edit.setText(self._config.diarization.huggingface_token)
        self._num_speakers_spin.setValue(self._config.diarization.num_speakers)
        self._max_speakers_spin.setValue(self._config.diarization.max_speakers)
        self._set_combo_value(self._engine_combo, self._config.stt.engine)
        self._set_combo_value(self._model_combo, self._config.stt.model)
        self._set_combo_value(self._device_combo, self._config.stt.device)

        self._api_base_edit.setText(self._config.stt.api_base)
        self._api_key_edit.setText(self._config.stt.api_key)
        self._api_model_edit.setText(self._config.stt.api_model)

        # VAD & anti-hallucination
        vad = self._config.vad
        self._speech_threshold_spin.setValue(vad.speech_threshold)
        self._min_duration_spin.setValue(vad.min_segment_duration_ms)
        self._min_rms_spin.setValue(vad.min_segment_rms)
        self._min_active_ratio_spin.setValue(vad.min_active_ratio)
        self._min_speech_frames_spin.setValue(vad.min_speech_frames)
        self._silero_checkbox.setChecked(vad.use_silero_vad)
        self._silero_prob_spin.setValue(vad.silero_speech_prob)

        stt = self._config.stt
        self._vad_filter_checkbox.setChecked(stt.vad_filter)
        self._no_speech_spin.setValue(stt.no_speech_threshold)
        self._log_prob_spin.setValue(stt.log_prob_threshold)
        self._comp_ratio_spin.setValue(stt.compression_ratio_threshold)

        self._match_stt_provider()
        self._sync_engine_state()

    def _match_stt_provider(self) -> None:
        current_base = self._config.stt.api_base.strip().rstrip("/")
        for name, preset in STT_API_PRESETS.items():
            if name == "Custom":
                continue
            if preset["api_base"].rstrip("/") == current_base:
                index = self._stt_provider_combo.findText(name)
                if index >= 0:
                    self._stt_provider_combo.setCurrentIndex(index)
                return
        index = self._stt_provider_combo.findText("Custom")
        if index >= 0:
            self._stt_provider_combo.setCurrentIndex(index)

    def _set_combo_value(self, combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _sync_engine_state(self) -> None:
        engine = self._engine_combo.currentData()
        using_local = engine == "faster-whisper"
        speaker_strategy = self._speaker_strategy_combo.currentData()
        source = self._source_combo.currentData()
        using_pyannote = speaker_strategy == "pyannote"

        self._local_section.setVisible(using_local)
        self._api_section.setVisible(not using_local)
        self._diarization_section.setVisible(using_pyannote)

        if using_pyannote and source == "both":
            self._hint_label.setText(
                "Pyannote diarization hien chi dung cho 1 nguon audio duy nhat. Khi chon Mic + System, hay dung speaker labeling theo source."
            )
            self._hint_label.setStyleSheet("font-size: 11px; color: #ffcc80;")
            return

        if using_pyannote:
            self._hint_label.setText(
                "Pyannote diarization chay local de gan speaker tren cung 1 luong audio. Can Hugging Face token va quyen truy cap model pyannote."
            )
            self._hint_label.setStyleSheet("font-size: 11px; color: #90caf9;")
            return

        if speaker_strategy == "language" and source == "both":
            self._hint_label.setText(
                "Speaker labeling theo language chi dung cho 1 nguon audio. Khi chon Mic + System, app van gan Speaker theo source."
            )
            self._hint_label.setStyleSheet("font-size: 11px; color: #ffcc80;")
            return

        if speaker_strategy == "language":
            self._hint_label.setText(
                "Gan Speaker theo ngon ngu phat hien duoc. Phu hop nhat khi 1 nguoi noi ngon ngu nguon va 1 nguoi noi ngon ngu dich tren cung 1 luong audio."
            )
            self._hint_label.setStyleSheet("font-size: 11px; color: #90caf9;")
            return

        if using_local:
            current_model = self._model_combo.currentData()
            if current_model and not is_model_downloaded(current_model):
                self._hint_label.setText(
                    "Model chua duoc tai. Bam 'Models' o header de tai truoc khi Start."
                )
                self._hint_label.setStyleSheet("font-size: 11px; color: #ffb74d;")
            else:
                self._hint_label.setText(
                    "Su dung Whisper local. System audio uu tien WASAPI loopback."
                )
                self._hint_label.setStyleSheet("font-size: 11px; color: #aaaaaa;")
        else:
            self._hint_label.setText(
                "Su dung API de speech-to-text. Nhap Base URL, API Key va Model."
            )
            self._hint_label.setStyleSheet("font-size: 11px; color: #aaaaaa;")

    def _on_stt_provider_changed(self, provider_name: str) -> None:
        preset = STT_API_PRESETS.get(provider_name)
        if not preset:
            return

        if preset["api_base"]:
            self._api_base_edit.setText(preset["api_base"])
        if preset["api_model"]:
            self._api_model_edit.setText(preset["api_model"])

    def _toggle_key_visibility(self) -> None:
        if self._api_key_edit.echoMode() == QLineEdit.EchoMode.Password:
            self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._toggle_key_btn.setText("Hide")
        else:
            self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._toggle_key_btn.setText("Show")

    def _toggle_hf_visibility(self) -> None:
        if self._hf_token_edit.echoMode() == QLineEdit.EchoMode.Password:
            self._hf_token_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._toggle_hf_btn.setText("Hide")
        else:
            self._hf_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._toggle_hf_btn.setText("Show")

    def _save_and_close(self) -> None:
        source = self._source_combo.currentData()
        speaker_strategy = self._speaker_strategy_combo.currentData()
        engine = self._engine_combo.currentData()
        model = self._model_combo.currentData()
        device = self._device_combo.currentData()

        if engine == "faster-whisper":
            if not model:
                QMessageBox.warning(self, "Loi", "Can chon model Whisper.")
                return
        else:
            api_base = self._api_base_edit.text().strip()
            api_key = self._api_key_edit.text().strip()
            api_model = self._api_model_edit.text().strip()
            if not api_base:
                QMessageBox.warning(self, "Loi", "Base URL khong duoc de trong.")
                return
            if not api_key:
                QMessageBox.warning(self, "Loi", "API Key khong duoc de trong.")
                return
            if not api_model:
                QMessageBox.warning(self, "Loi", "Model khong duoc de trong.")
                return

        if speaker_strategy == "pyannote":
            if source == "both":
                QMessageBox.warning(
                    self,
                    "Loi",
                    "Pyannote diarization hien chi ho tro 1 nguon audio duy nhat.",
                )
                return
            if not self._hf_token_edit.text().strip():
                QMessageBox.warning(
                    self,
                    "Loi",
                    "Can Hugging Face token de dung pyannote diarization.",
                )
                return

        self._config.audio.source = source
        self._config.audio.speaker_strategy = speaker_strategy

        self._config.diarization.enabled = speaker_strategy == "pyannote"
        self._config.diarization.huggingface_token = self._hf_token_edit.text().strip()
        self._config.diarization.num_speakers = self._num_speakers_spin.value()
        self._config.diarization.max_speakers = self._max_speakers_spin.value()

        self._config.stt.engine = engine
        if model:
            self._config.stt.model = model
        if device:
            self._config.stt.device = device
        self._config.stt.api_base = self._api_base_edit.text().strip()
        self._config.stt.api_key = self._api_key_edit.text().strip()
        self._config.stt.api_model = self._api_model_edit.text().strip() or "whisper-1"

        # VAD + anti-hallucination
        self._config.vad.speech_threshold = float(self._speech_threshold_spin.value())
        self._config.vad.min_segment_duration_ms = int(self._min_duration_spin.value())
        self._config.vad.min_segment_rms = float(self._min_rms_spin.value())
        self._config.vad.min_active_ratio = float(self._min_active_ratio_spin.value())
        self._config.vad.min_speech_frames = int(self._min_speech_frames_spin.value())
        self._config.vad.use_silero_vad = bool(self._silero_checkbox.isChecked())
        self._config.vad.silero_speech_prob = float(self._silero_prob_spin.value())

        self._config.stt.vad_filter = bool(self._vad_filter_checkbox.isChecked())
        self._config.stt.no_speech_threshold = float(self._no_speech_spin.value())
        self._config.stt.log_prob_threshold = float(self._log_prob_spin.value())
        self._config.stt.compression_ratio_threshold = float(self._comp_ratio_spin.value())

        save_config_section(
            "audio",
            {
                "source": self._config.audio.source,
                "speaker_strategy": self._config.audio.speaker_strategy,
                "device_index": self._config.audio.device_index,
                "sample_rate": self._config.audio.sample_rate,
                "channels": self._config.audio.channels,
                "blocksize": self._config.audio.blocksize,
            },
        )
        save_config_section(
            "diarization",
            {
                "enabled": self._config.diarization.enabled,
                "provider": self._config.diarization.provider,
                "model": self._config.diarization.model,
                "huggingface_token": self._config.diarization.huggingface_token,
                "device": self._config.diarization.device,
                "window_ms": self._config.diarization.window_ms,
                "max_speakers": self._config.diarization.max_speakers,
                "num_speakers": self._config.diarization.num_speakers,
            },
        )
        save_config_section(
            "vad",
            {
                "speech_threshold": self._config.vad.speech_threshold,
                "min_speech_frames": self._config.vad.min_speech_frames,
                "silence_frames_to_end": self._config.vad.silence_frames_to_end,
                "max_speech_frames": self._config.vad.max_speech_frames,
                "frame_ms": self._config.vad.frame_ms,
                "min_segment_duration_ms": self._config.vad.min_segment_duration_ms,
                "min_segment_rms": self._config.vad.min_segment_rms,
                "min_active_ratio": self._config.vad.min_active_ratio,
                "use_silero_vad": self._config.vad.use_silero_vad,
                "silero_speech_prob": self._config.vad.silero_speech_prob,
            },
        )
        save_config_section(
            "stt",
            {
                "engine": self._config.stt.engine,
                "model": self._config.stt.model,
                "device": self._config.stt.device,
                "compute_type": self._config.stt.compute_type,
                "language": self._config.stt.language,
                "beam_size": self._config.stt.beam_size,
                "api_base": self._config.stt.api_base,
                "api_key": self._config.stt.api_key,
                "api_model": self._config.stt.api_model,
                "vad_filter": self._config.stt.vad_filter,
                "no_speech_threshold": self._config.stt.no_speech_threshold,
                "log_prob_threshold": self._config.stt.log_prob_threshold,
                "compression_ratio_threshold": self._config.stt.compression_ratio_threshold,
                "initial_prompt": self._config.stt.initial_prompt,
                "hallucination_blocklist": self._config.stt.hallucination_blocklist,
            },
        )

        self.accept()
