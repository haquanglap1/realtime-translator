"""Silero VAD wrapper — optional, lazy-loaded.

Silero VAD là deep-learning VAD nhẹ (~2MB, ONNX). Phân biệt speech thật
với noise/typing/clicks tốt hơn energy-based RMS.

Cài đặt: pip install silero-vad

Dùng:
    gate = SileroVADGate(threshold=0.5)
    if gate.has_speech(audio_16k):
        ...
"""

from __future__ import annotations

from typing import Optional

import numpy as np


class SileroUnavailableError(RuntimeError):
    pass


class SileroVADGate:
    """Kiểm tra 1 audio buffer có chứa speech không bằng Silero VAD.

    Thread-safe: mỗi instance giữ 1 model. Nếu dùng trên nhiều thread
    nên lock hoặc tạo instance riêng.
    """

    _SAMPLE_RATE = 16000
    _WINDOW_SIZE = 512  # Silero yêu cầu đúng 512 samples/window tại 16kHz

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        self._model = None
        self._import_error: Optional[str] = None
        self._load_model()

    def _load_model(self) -> None:
        try:
            # silero-vad package exposes load_silero_vad()
            from silero_vad import load_silero_vad
        except ImportError as exc:
            self._import_error = (
                "silero-vad chưa cài. Chạy: pip install silero-vad"
            )
            print(f"[silero-vad] {self._import_error}")
            return

        try:
            self._model = load_silero_vad()
            print("[silero-vad] Model loaded.")
        except Exception as exc:
            self._import_error = f"Không load được Silero VAD: {exc}"
            print(f"[silero-vad] {self._import_error}")
            self._model = None

    @property
    def available(self) -> bool:
        return self._model is not None

    def max_speech_prob(self, audio: np.ndarray) -> float:
        """Trả về xác suất speech cao nhất trên các window 512-samples.

        Nếu model chưa load hoặc audio rỗng → trả 0.0.
        """
        if self._model is None or audio is None or len(audio) < self._WINDOW_SIZE:
            return 0.0

        # Silero yêu cầu torch tensor float32 mono
        try:
            import torch
        except ImportError:
            return 0.0

        try:
            tensor = torch.from_numpy(audio.astype(np.float32))
        except Exception:
            return 0.0

        max_prob = 0.0
        # Reset state giữa các lần gọi để không leak giữa segments
        try:
            self._model.reset_states()
        except AttributeError:
            pass

        for start in range(0, len(tensor) - self._WINDOW_SIZE + 1, self._WINDOW_SIZE):
            window = tensor[start : start + self._WINDOW_SIZE]
            try:
                prob = float(self._model(window, self._SAMPLE_RATE).item())
            except Exception as exc:
                print(f"[silero-vad] inference error: {exc}")
                return 0.0
            if prob > max_prob:
                max_prob = prob

        return max_prob

    def has_speech(self, audio: np.ndarray) -> bool:
        return self.max_speech_prob(audio) >= self.threshold
