"""Kiểm tra bản cập nhật qua GitHub Releases API.

Pattern sử dụng:
    from utils.updater import check_update_async
    check_update_async(on_available=lambda info: show_dialog(info))

Thread-safe, không block UI. Nếu không có mạng hoặc API lỗi → silent fail.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from utils.version import GITHUB_REPO, __version__


@dataclass
class UpdateInfo:
    version: str              # "0.5.0"
    tag: str                  # "v0.5.0"
    release_url: str          # https://github.com/.../releases/tag/v0.5.0
    download_url: Optional[str]  # Direct link tới installer (asset đầu tiên .exe/.zip)
    body: str                 # Release notes (markdown)


def _parse_version(v: str) -> tuple[int, ...]:
    """"v0.4.3" hoặc "0.4.3" → (0, 4, 3). Phần không phải số coi là 0."""
    v = v.lstrip("vV").strip()
    parts = v.split("-", 1)[0].split(".")
    result = []
    for p in parts:
        digits = "".join(ch for ch in p if ch.isdigit())
        result.append(int(digits) if digits else 0)
    return tuple(result)


def _is_newer(remote: str, local: str) -> bool:
    try:
        return _parse_version(remote) > _parse_version(local)
    except Exception:
        return False


def _pick_asset(assets: list[dict]) -> Optional[str]:
    """Ưu tiên .exe (installer), rồi .zip, rồi asset đầu tiên."""
    if not assets:
        return None
    for pattern in (".exe", ".msi", ".zip"):
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith(pattern):
                return asset.get("browser_download_url")
    return assets[0].get("browser_download_url")


def check_update_sync(timeout: float = 5.0) -> Optional[UpdateInfo]:
    """Blocking check. Trả về UpdateInfo nếu có bản mới, None nếu không."""
    if "YOUR_GITHUB_USER" in GITHUB_REPO:
        # Chưa cấu hình repo → skip check.
        return None

    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"realtime-translator/{__version__}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        print(f"[updater] Không kiểm tra được update: {exc}")
        return None
    except json.JSONDecodeError as exc:
        print(f"[updater] Response không phải JSON hợp lệ: {exc}")
        return None

    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        return None

    remote_version = tag.lstrip("vV")
    if not _is_newer(remote_version, __version__):
        return None

    return UpdateInfo(
        version=remote_version,
        tag=tag,
        release_url=data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases",
        download_url=_pick_asset(data.get("assets") or []),
        body=data.get("body") or "",
    )


def check_update_async(
    on_available: Callable[[UpdateInfo], None],
    timeout: float = 5.0,
) -> None:
    """Chạy check_update_sync trong daemon thread, gọi callback nếu có bản mới.

    Callback được gọi từ worker thread — UI framework nào cần marshal về main thread
    thì làm ở callback (ví dụ PyQt6 emit signal).
    """

    def _worker() -> None:
        info = check_update_sync(timeout=timeout)
        if info is not None:
            try:
                on_available(info)
            except Exception as exc:
                print(f"[updater] Callback lỗi: {exc}")

    thread = threading.Thread(target=_worker, name="updater", daemon=True)
    thread.start()
