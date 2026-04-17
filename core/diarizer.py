"""
Optional speaker diarization helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from utils.config import DiarizationConfig


@dataclass
class DiarizedTurn:
    start_ms: int
    end_ms: int
    speaker_id: str


class BaseDiarizer:
    def diarize_window(self, audio: np.ndarray, sample_rate: int) -> list[DiarizedTurn]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class PyannoteDiarizer(BaseDiarizer):
    def __init__(self, config: DiarizationConfig):
        self.config = config
        self._pipeline = None
        self._torch = None
        self._load_pipeline()

    def _load_pipeline(self) -> None:
        try:
            import torch
            from pyannote.audio import Pipeline
        except Exception as exc:
            raise RuntimeError(
                "pyannote.audio is not installed. Run `pip install pyannote.audio` first."
            ) from exc

        if not self.config.huggingface_token:
            raise RuntimeError(
                "Missing Hugging Face token for pyannote diarization."
            )

        self._torch = torch
        self._pipeline = Pipeline.from_pretrained(
            self.config.model,
            token=self.config.huggingface_token,
        )

        device = self.config.device.lower().strip()
        if device == "cuda" and torch.cuda.is_available():
            self._pipeline.to(torch.device("cuda"))
        else:
            self._pipeline.to(torch.device("cpu"))

    def diarize_window(self, audio: np.ndarray, sample_rate: int) -> list[DiarizedTurn]:
        if self._pipeline is None or self._torch is None or len(audio) == 0:
            return []

        waveform = self._torch.from_numpy(audio).float().unsqueeze(0)
        kwargs: dict[str, int] = {}
        if self.config.num_speakers > 0:
            kwargs["num_speakers"] = self.config.num_speakers
        else:
            kwargs["max_speakers"] = max(1, self.config.max_speakers)

        output = self._pipeline(
            {"waveform": waveform, "sample_rate": sample_rate},
            **kwargs,
        )
        annotation = getattr(output, "exclusive_speaker_diarization", None) or output

        turns: list[DiarizedTurn] = []
        for turn, _, speaker in annotation.itertracks(yield_label=True):
            turns.append(
                DiarizedTurn(
                    start_ms=max(0, int(turn.start * 1000)),
                    end_ms=max(0, int(turn.end * 1000)),
                    speaker_id=str(speaker),
                )
            )
        return turns

    def close(self) -> None:
        self._pipeline = None
        self._torch = None


def create_diarizer(config: DiarizationConfig) -> Optional[BaseDiarizer]:
    if not config.enabled:
        return None
    if config.provider != "pyannote":
        raise ValueError(f"Unsupported diarization provider: {config.provider}")
    return PyannoteDiarizer(config)
