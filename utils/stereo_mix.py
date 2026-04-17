"""Detect and help enable Stereo Mix (loopback audio) on Windows."""

from __future__ import annotations

import subprocess
import sys
from typing import Optional


def check_loopback_available() -> bool:
    """Check if a loopback-capable input device exists in sounddevice."""
    try:
        from core.audio_capture import find_loopback_device
        return find_loopback_device() is not None
    except Exception:
        return False


def open_sound_settings_recording() -> bool:
    """Open Windows Sound Settings → Recording tab."""
    if sys.platform != "win32":
        return False
    try:
        # mmsys.cpl ,1 opens the Recording tab directly
        subprocess.Popen(["control", "mmsys.cpl", ",1"])
        return True
    except Exception:
        return False


INSTRUCTIONS_VI = """\
Stereo Mix chua duoc bat. De bat audio loopback (nghe am thanh he thong):

1. Click chuot phai vao vung trong trong tab Recording
2. Chon "Show Disabled Devices"
3. Click chuot phai vao "Stereo Mix" → chon "Enable"
4. Click OK va khoi dong lai app

Neu khong thay Stereo Mix:
- Cap nhat driver Realtek Audio
- Hoac dung microphone (--source mic)
"""

INSTRUCTIONS_EN = """\
Stereo Mix is not enabled. To capture system audio (loopback):

1. Right-click empty space in the Recording tab
2. Select "Show Disabled Devices"
3. Right-click "Stereo Mix" → select "Enable"
4. Click OK and restart the app

If Stereo Mix is not listed:
- Update your Realtek Audio driver
- Or use microphone mode (--source mic)
"""


def get_instructions() -> str:
    """Return setup instructions (Vietnamese)."""
    return INSTRUCTIONS_VI
