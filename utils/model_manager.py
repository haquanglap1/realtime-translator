"""Backend logic for managing Whisper model downloads."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Callable, Optional

# Model registry: name → metadata
WHISPER_MODELS: dict[str, dict] = {
    "tiny":           {"size_mb": 77,   "repo": "Systran/faster-whisper-tiny"},
    "base":           {"size_mb": 145,  "repo": "Systran/faster-whisper-base"},
    "small":          {"size_mb": 484,  "repo": "Systran/faster-whisper-small"},
    "medium":         {"size_mb": 1500, "repo": "Systran/faster-whisper-medium"},
    "large-v3":       {"size_mb": 3000, "repo": "Systran/faster-whisper-large-v3"},
    "large-v3-turbo": {"size_mb": 1700, "repo": "Systran/faster-whisper-large-v3-turbo"},
}


def _format_size(mb: int) -> str:
    if mb >= 1000:
        return f"{mb / 1000:.1f} GB"
    return f"{mb} MB"


def get_model_display_size(model_name: str) -> str:
    info = WHISPER_MODELS.get(model_name)
    return _format_size(info["size_mb"]) if info else "?"


def get_cache_dir() -> Path:
    """Return the HuggingFace cache directory."""
    import os
    hf_home = os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")
    return Path(hf_home) / "hub"


def get_model_cache_path(model_name: str) -> Optional[Path]:
    """Return the expected cache directory for a model."""
    info = WHISPER_MODELS.get(model_name)
    if not info:
        return None
    # HF cache format: models--{org}--{name}
    repo = info["repo"].replace("/", "--")
    return get_cache_dir() / f"models--{repo}"


def is_model_downloaded(model_name: str) -> bool:
    """Check if model is downloaded and has snapshot with model.bin."""
    cache_path = get_model_cache_path(model_name)
    if cache_path is None or not cache_path.exists():
        return False

    snapshots = cache_path / "snapshots"
    if not snapshots.exists():
        return False

    # Check at least one snapshot directory has model.bin
    for snap_dir in snapshots.iterdir():
        if snap_dir.is_dir() and (snap_dir / "model.bin").exists():
            return True

    return False


def get_downloaded_models() -> list[str]:
    """Return list of model names that are downloaded."""
    return [name for name in WHISPER_MODELS if is_model_downloaded(name)]


def delete_model(model_name: str) -> bool:
    """Delete a downloaded model from cache."""
    cache_path = get_model_cache_path(model_name)
    if cache_path is None or not cache_path.exists():
        return False
    try:
        shutil.rmtree(cache_path)
        return True
    except Exception as e:
        print(f"[model_manager] Failed to delete {model_name}: {e}")
        return False


# ── Download manager ──────────────────────────────────────────────────────────

class ModelDownloader:
    """Thread-safe model downloader. Only one download at a time."""

    _is_downloading = False
    _lock = threading.Lock()

    @classmethod
    def is_busy(cls) -> bool:
        return cls._is_downloading

    @classmethod
    def download(
        cls,
        model_name: str,
        on_progress: Optional[Callable[[float], None]] = None,
        on_complete: Optional[Callable[[bool, str], None]] = None,
    ) -> None:
        """
        Start downloading a model in a background thread.

        on_progress(fraction): 0.0 → 1.0
        on_complete(success, message): called when done
        """
        with cls._lock:
            if cls._is_downloading:
                if on_complete:
                    on_complete(False, "Another download is in progress")
                return
            cls._is_downloading = True

        thread = threading.Thread(
            target=cls._download_worker,
            args=(model_name, on_progress, on_complete),
            name=f"model-download-{model_name}",
            daemon=True,
        )
        thread.start()

    @classmethod
    def _download_worker(
        cls,
        model_name: str,
        on_progress: Optional[Callable[[float], None]],
        on_complete: Optional[Callable[[bool, str], None]],
    ) -> None:
        try:
            info = WHISPER_MODELS.get(model_name)
            if not info:
                raise ValueError(f"Unknown model: {model_name}")

            from huggingface_hub import snapshot_download

            # Download the model repo
            # huggingface_hub handles caching, resume, etc.
            snapshot_download(
                repo_id=info["repo"],
                # No direct progress callback in snapshot_download,
                # but it uses tqdm internally which shows in console
            )

            # Signal completion
            if on_progress:
                on_progress(1.0)

            if is_model_downloaded(model_name):
                if on_complete:
                    on_complete(True, f"Model '{model_name}' downloaded successfully")
            else:
                if on_complete:
                    on_complete(False, f"Download finished but model files not found")

        except Exception as e:
            if on_complete:
                on_complete(False, str(e))
        finally:
            with cls._lock:
                cls._is_downloading = False
