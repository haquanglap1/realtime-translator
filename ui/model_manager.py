"""PyQt6 dialog for managing Whisper model downloads."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from utils.model_manager import (
    WHISPER_MODELS, ModelDownloader, delete_model,
    get_model_display_size, is_model_downloaded,
)


# ── Styling ───────────────────────────────────────────────────────────────────

DIALOG_STYLE = """
QDialog {
    background-color: #1a1a1a;
    color: #ffffff;
}
QLabel {
    color: #ffffff;
}
QTableWidget {
    background-color: #222222;
    color: #ffffff;
    border: 1px solid #333333;
    gridline-color: #333333;
    selection-background-color: #3a3a3a;
}
QTableWidget::item {
    padding: 4px 8px;
}
QHeaderView::section {
    background-color: #2a2a2a;
    color: #cccccc;
    border: 1px solid #333333;
    padding: 4px 8px;
    font-weight: bold;
}
QPushButton {
    border: none;
    border-radius: 4px;
    padding: 6px 16px;
    font-size: 12px;
    font-weight: bold;
}
QPushButton:disabled {
    background-color: #444444;
    color: #888888;
}
QProgressBar {
    border: 1px solid #555555;
    border-radius: 3px;
    background-color: #333333;
    text-align: center;
    color: #ffffff;
    font-size: 10px;
}
QProgressBar::chunk {
    background-color: #4CAF50;
    border-radius: 2px;
}
"""

STATUS_DOWNLOADED = "Da tai"
STATUS_NOT_DOWNLOADED = "Chua tai"
STATUS_DOWNLOADING = "Dang tai..."


class ModelManagerDialog(QDialog):
    """Dialog for downloading and managing Whisper models."""

    # Signals for thread-safe UI updates
    _progress_signal = pyqtSignal(str, float)       # model_name, fraction
    _complete_signal = pyqtSignal(str, bool, str)    # model_name, success, message

    def __init__(self, current_model: str = "medium", parent=None):
        super().__init__(parent)
        self.current_model = current_model
        self._downloading_model: Optional[str] = None

        self.setWindowTitle("Whisper Model Manager")
        self.setMinimumSize(550, 400)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint
        )

        self._build_ui()
        self._refresh_table()

        # Connect thread-safe signals
        self._progress_signal.connect(self._on_progress)
        self._complete_signal.connect(self._on_complete)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Title
        title = QLabel("Quan ly Model Whisper")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)

        subtitle = QLabel("Tai model truoc khi su dung. Model lon cho do chinh xac cao hon.")
        subtitle.setStyleSheet("font-size: 11px; color: #aaaaaa;")
        layout.addWidget(subtitle)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Model", "Kich thuoc", "Trang thai", ""])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 90)
        self._table.setColumnWidth(2, 120)
        self._table.setColumnWidth(3, 100)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table)

        # Footer
        footer = QHBoxLayout()
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("font-size: 11px; color: #aaaaaa;")
        footer.addWidget(self._info_label)
        footer.addStretch()

        close_btn = QPushButton("Dong")
        close_btn.setStyleSheet("""
            QPushButton { background-color: #555555; color: white; }
            QPushButton:hover { background-color: #666666; }
        """)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

    def _refresh_table(self) -> None:
        models = list(WHISPER_MODELS.keys())
        self._table.setRowCount(len(models))

        for row, model_name in enumerate(models):
            downloaded = is_model_downloaded(model_name)
            is_current = model_name == self.current_model
            is_downloading = self._downloading_model == model_name

            # Column 0: model name
            name_text = model_name
            if is_current:
                name_text += "  (dang dung)"
            name_item = QTableWidgetItem(name_text)
            if is_current:
                name_item.setForeground(Qt.GlobalColor.cyan)
            self._table.setItem(row, 0, name_item)

            # Column 1: size
            size_item = QTableWidgetItem(get_model_display_size(model_name))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 1, size_item)

            # Column 2: status
            if is_downloading:
                progress = QProgressBar()
                progress.setRange(0, 0)  # indeterminate
                progress.setFixedHeight(20)
                self._table.setCellWidget(row, 2, progress)
            else:
                status_item = QTableWidgetItem(STATUS_DOWNLOADED if downloaded else STATUS_NOT_DOWNLOADED)
                status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if downloaded:
                    status_item.setForeground(Qt.GlobalColor.green)
                else:
                    status_item.setForeground(Qt.GlobalColor.gray)
                self._table.setItem(row, 2, status_item)

            # Column 3: action button
            if is_downloading:
                btn = QPushButton("...")
                btn.setEnabled(False)
            elif downloaded:
                btn = QPushButton("Xoa")
                btn.setStyleSheet("""
                    QPushButton { background-color: #d32f2f; color: white; }
                    QPushButton:hover { background-color: #f44336; }
                """)
                btn.clicked.connect(lambda checked, m=model_name: self._on_delete(m))
                # Don't allow deleting the currently active model
                if is_current:
                    btn.setEnabled(False)
                    btn.setToolTip("Khong the xoa model dang su dung")
            else:
                btn = QPushButton("Tai")
                btn.setStyleSheet("""
                    QPushButton { background-color: #388e3c; color: white; }
                    QPushButton:hover { background-color: #4caf50; }
                """)
                btn.clicked.connect(lambda checked, m=model_name: self._on_download(m))

            # Disable all action buttons during download
            if ModelDownloader.is_busy() and not is_downloading:
                btn.setEnabled(False)

            self._table.setCellWidget(row, 3, btn)

        self._table.setRowHeight(0, 36)
        for row in range(self._table.rowCount()):
            self._table.setRowHeight(row, 36)

        # Update info
        downloaded = [m for m in models if is_model_downloaded(m)]
        self._info_label.setText(f"Da tai: {len(downloaded)}/{len(models)} model")

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_download(self, model_name: str) -> None:
        self._downloading_model = model_name
        self._refresh_table()

        def on_progress(fraction: float):
            self._progress_signal.emit(model_name, fraction)

        def on_complete(success: bool, message: str):
            self._complete_signal.emit(model_name, success, message)

        ModelDownloader.download(
            model_name,
            on_progress=on_progress,
            on_complete=on_complete,
        )

    def _on_delete(self, model_name: str) -> None:
        reply = QMessageBox.question(
            self,
            "Xac nhan xoa",
            f"Xoa model '{model_name}'?\nBan se can tai lai neu muon dung.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_model(model_name)
            self._refresh_table()

    # ── Signal handlers (UI thread) ───────────────────────────────────────────

    def _on_progress(self, model_name: str, fraction: float) -> None:
        # Find the progress bar for this model and update it
        models = list(WHISPER_MODELS.keys())
        row = models.index(model_name) if model_name in models else -1
        if row >= 0:
            widget = self._table.cellWidget(row, 2)
            if isinstance(widget, QProgressBar):
                widget.setRange(0, 100)
                widget.setValue(int(fraction * 100))

    def _on_complete(self, model_name: str, success: bool, message: str) -> None:
        self._downloading_model = None
        self._refresh_table()

        if success:
            self._info_label.setText(f"Model '{model_name}' da tai xong!")
            self._info_label.setStyleSheet("font-size: 11px; color: #4caf50;")
        else:
            self._info_label.setText(f"Loi: {message}")
            self._info_label.setStyleSheet("font-size: 11px; color: #f44336;")

        # Reset info label style after 5 seconds
        QTimer.singleShot(5000, lambda: self._info_label.setStyleSheet("font-size: 11px; color: #aaaaaa;"))
