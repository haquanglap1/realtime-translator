"""
RealtimeTranslator - Entry point.

Chay:
    python main.py
    python main.py --config path/to/settings.yaml
    python main.py --source mic --model small --device cpu
"""

from __future__ import annotations

import argparse
import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from PyQt6.QtWidgets import QApplication

from core.pipeline import Pipeline
from core.transcriber import TranscriptSegment
from ui.main_window import MainWindow
from utils.config import load_config


def parse_args():
    parser = argparse.ArgumentParser(description="Real-time translator")
    parser.add_argument(
        "--config",
        default=None,
        help="\u0110\u01b0\u1eddng d\u1eabn t\u1edbi settings.yaml",
    )
    parser.add_argument(
        "--source",
        choices=["mic", "loopback", "both"],
        default=None,
        help="Ngu\u1ed3n \u00e2m thanh (override settings.yaml)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Whisper model: tiny/base/small/medium/large-v3",
    )
    parser.add_argument(
        "--device",
        choices=["cuda", "cpu"],
        default=None,
        help="Device cho faster-whisper",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="Li\u1ec7t k\u00ea audio devices r\u1ed3i tho\u00e1t",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.list_devices:
        from core.audio_capture import list_devices

        print("\n=== Audio Devices ===")
        for dev in list_devices():
            tag = ""
            if dev["max_input"] > 0:
                tag += "[IN]"
            if dev["max_output"] > 0:
                tag += "[OUT]"
            print(f"  [{dev['index']:2d}] {tag:8s} {dev['hostapi']:10s} | {dev['name']}")
        print()
        return

    config = load_config(args.config)

    if args.source:
        config.audio.source = args.source
    if args.model:
        config.stt.model = args.model
    if args.device:
        config.stt.device = args.device

    if config.stt.engine == "faster-whisper" and config.stt.device == "cuda":
        from utils.torch_setup import ensure_torch

        print("Checking PyTorch + CUDA...")
        ensure_torch()

    app = QApplication(sys.argv)
    app.setApplicationName("RealtimeTranslator")

    window = MainWindow(config)

    def on_result(seg: TranscriptSegment) -> None:
        window.transcript_received.emit(seg)

    def on_translation(segs: list[TranscriptSegment]) -> None:
        window.translation_received.emit(segs)

    def on_status(status: str) -> None:
        window.status_changed.emit(status)

    def on_rewrite_state_changed(is_running: bool) -> None:
        window.rewrite_state_changed.emit(is_running)

    pipeline = Pipeline(
        config,
        on_result=on_result,
        on_translation=on_translation,
        on_status=on_status,
        on_rewrite_state_changed=on_rewrite_state_changed,
    )
    window.set_pipeline(pipeline)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
