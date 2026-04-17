"""
Main overlay window - PyQt6.
"""

from __future__ import annotations

from collections import deque
from typing import Optional

from PyQt6.QtCore import QPoint, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

from core.transcriber import TranscriptSegment
from utils.config import AppConfig
from utils.updater import UpdateInfo, check_update_async
from utils.version import __version__


ACCENT_GREEN = "#4CAF50"
ACCENT_RED = "#F44336"
ACCENT_BLUE = "#1976D2"
TEXT_WHITE = "#FFFFFF"
TEXT_DIM = "#AAAAAA"
TEXT_TRANSLATED = "#81D4FA"
TEXT_TRANS_OLD = "#B0BEC5"


class TranscriptLine:
    def __init__(self, seg: TranscriptSegment):
        self.seg_id = seg.id
        self.original = seg.text
        self.translated: Optional[str] = seg.translated
        self.language = seg.language
        self.speaker_label = seg.speaker_label or "Speaker 1"
        self.start_ms = seg.start_ms
        self.end_ms = seg.end_ms


class MainWindow(QWidget):
    transcript_received = pyqtSignal(object)
    translation_received = pyqtSignal(object)
    status_changed = pyqtSignal(str)
    rewrite_state_changed = pyqtSignal(bool)
    update_available = pyqtSignal(object)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._app_config = config
        self.config = config.ui
        self._lines: deque[TranscriptLine] = deque(maxlen=100)
        self._drag_pos: Optional[QPoint] = None
        self._pipeline = None
        self._rewrite_in_progress = False
        self.display_mode = 0  # 0: song ngu, 1: chi dich, 2: chi goc

        self._build_ui()
        self._apply_position()
        self.setWindowTitle(f"RealtimeTranslator v{__version__}")

        self.transcript_received.connect(self._on_transcript)
        self.translation_received.connect(self._on_translation)
        self.status_changed.connect(self._on_status)
        self.rewrite_state_changed.connect(self._on_rewrite_state_changed)
        self.update_available.connect(self._on_update_available)

        # Kiểm tra bản mới trong background (non-blocking, silent fail)
        check_update_async(on_available=self.update_available.emit)

    def _build_ui(self) -> None:
        cfg = self.config

        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(400, 120)
        self.resize(cfg.width, cfg.height)
        self.setWindowOpacity(cfg.opacity)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = QWidget()
        self._header.setFixedHeight(38)
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(10, 0, 8, 0)

        title = QLabel("RealtimeTranslator")
        title.setStyleSheet(
            f"color: {TEXT_WHITE}; font-size: 12px; font-weight: bold;"
        )
        header_layout.addWidget(title)
        header_layout.addStretch()

        self._btn_mode = self._small_btn(
            "Mode: Song ng\u1eef",
            self._toggle_display_mode,
        )
        btn_models = self._small_btn("Models", self._open_model_manager)
        btn_stt = self._small_btn("STT", self._open_stt_config)
        btn_llm = self._small_btn("LLM", self._open_llm_config)
        btn_opacity_down = self._small_btn("A-", self._decrease_opacity)
        btn_opacity_up = self._small_btn("A+", self._increase_opacity)
        btn_bg_down = self._small_btn("B-", self._decrease_bg_opacity)
        btn_bg_up = self._small_btn("B+", self._increase_bg_opacity)
        btn_font_down = self._small_btn("T-", self._decrease_font)
        btn_font_up = self._small_btn("T+", self._increase_font)
        btn_clear = self._small_btn("Clear", self._clear_transcript)
        btn_exit = self._small_btn("Exit", self._exit_app)
        btn_exit.setStyleSheet(
            """
            QPushButton {
                background: rgba(244,67,54,180);
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                padding: 0 8px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover { background: rgba(244,67,54,230); }
            """
        )

        for btn in [
            self._btn_mode,
            btn_models,
            btn_stt,
            btn_llm,
            btn_opacity_down,
            btn_opacity_up,
            btn_bg_down,
            btn_bg_up,
            btn_font_down,
            btn_font_up,
            btn_clear,
            btn_exit,
        ]:
            header_layout.addWidget(btn)

        self._apply_panel_styles()
        root.addWidget(self._header)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setStyleSheet(
            """
            QScrollArea { border: none; background-color: transparent; }
            QScrollBar:vertical { width: 6px; background: transparent; }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,50);
                border-radius: 3px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            """
        )
        self._auto_scroll = True
        vbar = self._scroll_area.verticalScrollBar()

        def _on_scroll_range_changed(_min_val, max_val):
            if self._auto_scroll:
                vbar.setValue(max_val)

        def _on_scroll_value_changed(val):
            self._auto_scroll = val >= vbar.maximum() - 15

        vbar.rangeChanged.connect(_on_scroll_range_changed)
        vbar.valueChanged.connect(_on_scroll_value_changed)

        self._transcript_widget = QWidget()
        self._transcript_layout = QVBoxLayout(self._transcript_widget)
        self._transcript_layout.setContentsMargins(12, 8, 12, 8)
        self._transcript_layout.setSpacing(2)
        self._transcript_layout.addStretch()

        self._scroll_area.setWidget(self._transcript_widget)
        root.addWidget(self._scroll_area, stretch=1)

        self._footer = QWidget()
        self._footer.setFixedHeight(40)
        footer = self._footer
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(10, 0, 10, 0)

        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        footer_layout.addWidget(self._status_label)
        footer_layout.addStretch()

        self._start_btn = QPushButton("Start")
        self._start_btn.setFixedSize(110, 28)
        self._start_btn.setStyleSheet(self._btn_style(ACCENT_GREEN))
        self._start_btn.clicked.connect(self._toggle_pipeline)
        footer_layout.addWidget(self._start_btn)

        self._rewrite_btn = QPushButton("Rewrite")
        self._rewrite_btn.setFixedSize(110, 28)
        self._rewrite_btn.setStyleSheet(self._btn_style(ACCENT_BLUE))
        self._rewrite_btn.clicked.connect(self._rewrite_latest_transcript)
        footer_layout.addWidget(self._rewrite_btn)

        size_grip = QSizeGrip(footer)
        size_grip.setStyleSheet("width: 15px; height: 15px; background: transparent;")
        footer_layout.addWidget(
            size_grip,
            0,
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight,
        )

        root.addWidget(footer)
        self._update_action_buttons()

    def _small_btn(self, text: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(24)
        btn.setStyleSheet(
            """
            QPushButton {
                background: rgba(255,255,255,20);
                color: #CCCCCC;
                border: none;
                border-radius: 4px;
                padding: 0 8px;
                font-size: 10px;
            }
            QPushButton:hover { background: rgba(255,255,255,40); }
            """
        )
        btn.clicked.connect(slot)
        return btn

    @staticmethod
    def _btn_style(color: str) -> str:
        return f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{ opacity: 0.85; }}
        """

    def _build_segment_snapshot(self) -> list[TranscriptSegment]:
        return [
            TranscriptSegment(
                id=line.seg_id,
                text=line.original,
                language=line.language,
                start_ms=line.start_ms,
                end_ms=line.end_ms,
                duration_ms=max(0, line.end_ms - line.start_ms),
                engine_latency_ms=0,
                speaker_label=line.speaker_label,
                translated=line.translated,
            )
            for line in self._lines
        ]

    def _update_action_buttons(self) -> None:
        has_transcript = any(line.original.strip() for line in self._lines)
        can_rewrite = bool(
            self._pipeline
            and getattr(self._pipeline, "can_rewrite", False)
            and has_transcript
            and not self._rewrite_in_progress
        )
        if hasattr(self, "_rewrite_btn"):
            self._rewrite_btn.setEnabled(can_rewrite)

    def _apply_position(self) -> None:
        screen = QApplication.primaryScreen().geometry()
        pos = self.config.position
        w, h = self.config.width, self.config.height
        margin = 20

        if pos == "bottom-right":
            self.move(screen.width() - w - margin, screen.height() - h - margin - 50)
        elif pos == "bottom-left":
            self.move(margin, screen.height() - h - margin - 50)
        elif pos == "top-right":
            self.move(screen.width() - w - margin, margin + 30)
        elif pos == "top-left":
            self.move(margin, margin + 30)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, _event):
        self._drag_pos = None

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._pipeline and self._pipeline.is_running:
            self._save_transcript()
            self._pipeline.stop()
        event.accept()

    def set_pipeline(self, pipeline) -> None:
        self._pipeline = pipeline
        self._update_action_buttons()

    def _toggle_pipeline(self) -> None:
        if self._pipeline is None:
            return

        if self._pipeline.is_running:
            self._start_btn.setText("Start")
            self._start_btn.setStyleSheet(self._btn_style(ACCENT_GREEN))
            self._save_transcript()
            self._pipeline.stop()
        else:
            self._start_btn.setText("Stop")
            self._start_btn.setStyleSheet(self._btn_style(ACCENT_RED))
            try:
                self._pipeline.start()
            except Exception as exc:
                self._start_btn.setText("Start")
                self._start_btn.setStyleSheet(self._btn_style(ACCENT_GREEN))
                QMessageBox.warning(self, "Error", str(exc))
        self._update_action_buttons()

    def _rewrite_latest_transcript(self) -> None:
        if self._pipeline is None:
            return
        if not self._pipeline.can_rewrite:
            QMessageBox.information(
                self,
                "Rewrite",
                "H\u00e3y b\u1eadt LLM translation tr\u01b0\u1edbc khi d\u00f9ng Rewrite.",
            )
            return

        segments = self._build_segment_snapshot()
        if not segments:
            QMessageBox.information(
                self,
                "Rewrite",
                "Ch\u01b0a c\u00f3 transcript \u0111\u1ec3 rewrite.",
            )
            return

        try:
            self._rewrite_in_progress = True
            self._update_action_buttons()
            self._pipeline.rewrite_latest_transcript(segments)
        except Exception as exc:
            self._rewrite_in_progress = False
            self._update_action_buttons()
            QMessageBox.warning(self, "Rewrite", str(exc))

    def _save_transcript(self) -> None:
        save_dir = getattr(self._app_config.llm, "transcript_save_dir", "")
        if not save_dir or not self._lines:
            return

        import os
        from datetime import datetime

        if not os.path.isdir(save_dir):
            return

        filename = f"transcript_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
        file_path = os.path.join(save_dir, filename)

        try:
            with open(file_path, "w", encoding="utf-8") as file:
                for line in self._lines:
                    text = line.original.strip()
                    if text:
                        file.write(f"[{line.speaker_label}] {text}\n")
            print(
                f"[main_window] \u0110\u00e3 l\u01b0u b\u1ea3n ch\u00e9p l\u1eddi v\u00e0o: {file_path}"
            )
        except Exception as exc:
            print(
                f"[main_window] L\u1ed7i khi l\u01b0u b\u1ea3n ch\u00e9p l\u1eddi: {exc}"
            )

    def _open_model_manager(self) -> None:
        from ui.model_manager import ModelManagerDialog

        dialog = ModelManagerDialog(
            current_model=self._app_config.stt.model,
            parent=self,
        )
        dialog.exec()

    def _open_stt_config(self) -> None:
        if self._pipeline and self._pipeline.is_running:
            QMessageBox.information(
                self,
                "STT Configuration",
                "D\u1eebng pipeline tr\u01b0\u1edbc khi \u0111\u1ed5i audio source ho\u1eb7c Whisper model.",
            )
            return

        from ui.stt_config import STTConfigDialog

        dialog = STTConfigDialog(
            config=self._app_config,
            parent=self,
        )
        if dialog.exec():
            self._status_label.setText(
                f"STT updated: {self._app_config.audio.source}, {self._app_config.stt.model}"
            )

    def _open_llm_config(self) -> None:
        from ui.llm_config import LLMConfigDialog

        dialog = LLMConfigDialog(
            config=self._app_config.llm,
            parent=self,
        )
        if dialog.exec():
            if self._pipeline and not self._pipeline.is_running:
                self._status_label.setText("LLM config updated")
            self._update_action_buttons()

    def _exit_app(self) -> None:
        self.close()

    def _toggle_display_mode(self) -> None:
        self.display_mode = (self.display_mode + 1) % 3
        modes = [
            "Mode: Song ng\u1eef",
            "Mode: Ch\u1ec9 D\u1ecbch",
            "Mode: Ch\u1ec9 G\u1ed1c",
        ]
        self._btn_mode.setText(modes[self.display_mode])
        self._refresh_transcript()

    @pyqtSlot(object)
    def _on_transcript(self, seg: TranscriptSegment) -> None:
        line = TranscriptLine(seg)
        self._lines.append(line)
        self._refresh_transcript()
        self._update_action_buttons()

    @pyqtSlot(object)
    def _on_translation(self, segs: list) -> None:
        updates = {
            seg.id: seg.translated
            for seg in segs
            if seg.translated is not None
        }
        for line in self._lines:
            if line.seg_id in updates:
                line.translated = updates[line.seg_id]
        speaker_updates = {seg.id: seg.speaker_label for seg in segs if seg.speaker_label}
        for line in self._lines:
            if line.seg_id in speaker_updates:
                line.speaker_label = speaker_updates[line.seg_id]
        self._refresh_transcript()
        self._update_action_buttons()

    @pyqtSlot(str)
    def _on_status(self, status: str) -> None:
        self._status_label.setText(status)

    @pyqtSlot(bool)
    def _on_rewrite_state_changed(self, is_running: bool) -> None:
        self._rewrite_in_progress = is_running
        self._update_action_buttons()

    def _refresh_transcript(self) -> None:
        while self._transcript_layout.count() > 1:
            item = self._transcript_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        font_size = self.config.font_size

        for index, line in enumerate(self._lines):
            is_latest = index == len(self._lines) - 1
            color = self.config.font_color if is_latest else TEXT_DIM

            speaker_tag = QLabel(line.speaker_label)
            speaker_tag.setStyleSheet(
                f"""
                color: {'#FFE082' if is_latest else '#CFD8DC'};
                font-size: {max(self.config.font_size - 4, 10)}px;
                font-weight: bold;
                background: transparent;
                padding: 4px 0 0 0;
                """
            )
            self._transcript_layout.insertWidget(
                self._transcript_layout.count() - 1,
                speaker_tag,
            )

            if self.display_mode in (0, 2):
                orig_label = QLabel(line.original)
                orig_label.setWordWrap(True)
                orig_label.setStyleSheet(
                    f"""
                    color: {color};
                    font-size: {font_size}px;
                    font-weight: {'bold' if is_latest else 'normal'};
                    background: transparent;
                    padding: 1px 0 0 0;
                    """
                )
                self._transcript_layout.insertWidget(
                    self._transcript_layout.count() - 1,
                    orig_label,
                )

            if line.translated and self.display_mode in (0, 1):
                trans_color = TEXT_TRANSLATED if is_latest else TEXT_TRANS_OLD
                trans_font_size = (
                    max(font_size - 1, 12) if self.display_mode == 0 else font_size
                )
                trans_sentences = [
                    sentence.strip()
                    for sentence in line.translated.split("\n")
                    if sentence.strip()
                ]
                if not trans_sentences:
                    trans_sentences = [line.translated]

                for sentence in trans_sentences:
                    trans_label = QLabel(sentence)
                    trans_label.setWordWrap(True)
                    trans_label.setStyleSheet(
                        f"""
                        color: {trans_color};
                        font-size: {trans_font_size}px;
                        font-weight: bold;
                        background: transparent;
                        padding: 0 0 2px 8px;
                        text-shadow: 1px 1px 2px #000000;
                        """
                    )
                    self._transcript_layout.insertWidget(
                        self._transcript_layout.count() - 1,
                        trans_label,
                    )

    def _clear_transcript(self) -> None:
        self._lines.clear()
        self._refresh_transcript()
        self._update_action_buttons()

    def _increase_opacity(self) -> None:
        self.setWindowOpacity(min(1.0, self.windowOpacity() + 0.05))

    def _decrease_opacity(self) -> None:
        self.setWindowOpacity(max(0.2, self.windowOpacity() - 0.05))

    @pyqtSlot(object)
    def _on_update_available(self, info: UpdateInfo) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Có bản cập nhật")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(
            f"Bản mới <b>v{info.version}</b> đã có trên GitHub "
            f"(đang dùng v{__version__})."
        )
        preview = (info.body or "").strip()
        if len(preview) > 400:
            preview = preview[:400] + "..."
        if preview:
            box.setInformativeText(preview)
        open_btn = box.addButton("Mở trang tải", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Để sau", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            import webbrowser

            target = info.download_url or info.release_url
            webbrowser.open(target)

    def _apply_panel_styles(self) -> None:
        bg_alpha = int(max(0.0, min(1.0, self.config.transcript_bg_opacity)) * 255)
        # Header / footer hơi nhạt hơn chút để phân lớp trực quan
        chrome_alpha = min(255, bg_alpha + 10)
        self._header.setStyleSheet(
            f"""
            background-color: rgba(25,25,25,{chrome_alpha});
            border-radius: 8px 8px 0 0;
            """
        )
        self._transcript_widget.setStyleSheet(
            f"background-color: rgba(18,18,18,{bg_alpha});"
        )
        self._footer.setStyleSheet(
            f"""
            background-color: rgba(25,25,25,{chrome_alpha});
            border-radius: 0 0 8px 8px;
            """
        )

    def _increase_bg_opacity(self) -> None:
        self.config.transcript_bg_opacity = min(
            1.0, round(self.config.transcript_bg_opacity + 0.05, 2)
        )
        self._apply_panel_styles()

    def _decrease_bg_opacity(self) -> None:
        self.config.transcript_bg_opacity = max(
            0.0, round(self.config.transcript_bg_opacity - 0.05, 2)
        )
        self._apply_panel_styles()

    def _increase_font(self) -> None:
        self.config.font_size = min(60, self.config.font_size + 2)
        self._refresh_transcript()

    def _decrease_font(self) -> None:
        self.config.font_size = max(10, self.config.font_size - 2)
        self._refresh_transcript()
