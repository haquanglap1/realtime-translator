"""Log các text nghi là hallucination để user review và mở rộng blocklist.

File log: <project>/hallucinations.log (bị gitignore).
Format: timestamp \t source \t text
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

_LOG_PATH = Path(__file__).parent.parent / "hallucinations.log"
_LOCK = threading.Lock()


def log_hallucination(text: str, source: str = "unknown") -> None:
    """Append 1 dòng vào hallucinations.log. Silent fail nếu không ghi được."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp}\t{source}\t{text}\n"
    try:
        with _LOCK:
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line)
    except OSError as exc:
        print(f"[hallucination-log] ghi lỗi: {exc}")
