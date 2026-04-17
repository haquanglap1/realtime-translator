"""Auto-detect and install PyTorch with CUDA support."""

from __future__ import annotations

import importlib
import subprocess
import sys
from typing import Callable, Optional


# RTX 5070 (Blackwell sm_120) requires cu128 wheels
TORCH_INDEX_URL = "https://download.pytorch.org/whl/cu128"
TORCH_PACKAGES = ["torch", "torchvision", "torchaudio"]


def check_torch_cuda() -> dict:
    """Check if torch is installed and CUDA is available."""
    result = {
        "torch_installed": False,
        "cuda_available": False,
        "device_name": None,
        "torch_version": None,
    }

    try:
        import torch
        result["torch_installed"] = True
        result["torch_version"] = torch.__version__

        if torch.cuda.is_available():
            result["cuda_available"] = True
            result["device_name"] = torch.cuda.get_device_name(0)
    except ImportError:
        pass

    return result


def install_torch_cuda(
    on_progress: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Install PyTorch with CUDA 12.8 support via pip.
    Returns True on success.
    """
    log = on_progress or print

    cmd = [
        sys.executable, "-m", "pip", "install",
        *TORCH_PACKAGES,
        "--index-url", TORCH_INDEX_URL,
    ]
    log(f"Installing: {' '.join(TORCH_PACKAGES)} (cu128)...")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                # Show download progress and key status lines
                if any(kw in line.lower() for kw in ["downloading", "installing", "collected", "successfully", "requirement"]):
                    log(line)

        proc.wait()
        if proc.returncode != 0:
            log(f"pip install failed (exit code {proc.returncode})")
            return False

        # Invalidate import caches so new packages are visible
        importlib.invalidate_caches()
        return True

    except Exception as e:
        log(f"Install error: {e}")
        return False


def ensure_torch(on_status: Optional[Callable[[str], None]] = None) -> dict:
    """
    Ensure torch+CUDA is available. Install if missing.
    Returns check_torch_cuda() result after setup.
    """
    log = on_status or print

    status = check_torch_cuda()

    if status["cuda_available"]:
        log(f"PyTorch {status['torch_version']} + CUDA ready ({status['device_name']})")
        return status

    if status["torch_installed"] and not status["cuda_available"]:
        log(f"PyTorch {status['torch_version']} installed but CUDA not available. Reinstalling with CUDA...")
    else:
        log("PyTorch not found. Installing with CUDA support...")

    success = install_torch_cuda(on_progress=log)

    if success:
        # Re-check after install
        status = check_torch_cuda()
        if status["cuda_available"]:
            log(f"PyTorch {status['torch_version']} + CUDA ready ({status['device_name']})")
        else:
            log("PyTorch installed but CUDA still not available. Using CPU mode.")
    else:
        log("Failed to install PyTorch. Will use CPU mode (slower).")

    return status
