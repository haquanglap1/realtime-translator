"""
STT transcriber wrapper.
"""

from __future__ import annotations

import io
import time
import wave
from dataclasses import dataclass
from typing import Optional

import numpy as np

from utils.config import STTConfig


@dataclass
class TranscriptSegment:
    id: int
    text: str
    language: str
    start_ms: int
    end_ms: int
    duration_ms: int
    engine_latency_ms: int
    speaker_label: str = ""
    source_label: str = ""
    translated: Optional[str] = None


def is_hallucination(text: str, blocklist: list[str]) -> bool:
    """Check xem text có khớp với các câu Whisper hay ảo giác không.

    Match case-insensitive substring để bắt được cả biến thể
    (ví dụ "Thank you for watching!" vẫn match "thank you for watching").
    """
    if not text or not blocklist:
        return False
    lowered = text.lower().strip()
    if not lowered:
        return True
    for pattern in blocklist:
        if pattern and pattern.lower() in lowered:
            return True
    return False


class BaseTranscriber:
    def transcribe(
        self,
        audio: np.ndarray,
        start_ms: int,
        end_ms: int,
        seg_id: int,
    ) -> Optional[TranscriptSegment]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class FasterWhisperTranscriber(BaseTranscriber):
    def __init__(self, config: STTConfig):
        self.config = config
        self._model = None
        self._last_text = ""
        self._load_model()

    def _load_model(self) -> None:
        from faster_whisper import WhisperModel

        from utils.model_manager import WHISPER_MODELS, is_model_downloaded

        if (
            self.config.model in WHISPER_MODELS
            and not is_model_downloaded(self.config.model)
        ):
            raise RuntimeError(
                f"Model '{self.config.model}' ch\u01b0a \u0111\u01b0\u1ee3c t\u1ea3i. "
                "M\u1edf Model Manager (n\u00fat 'Models' tr\u00ean header) \u0111\u1ec3 t\u1ea3i model."
            )

        device = self.config.device
        compute_type = self.config.compute_type

        try:
            import torch

            if device == "cuda" and not torch.cuda.is_available():
                print("[transcriber] CUDA not available, using CPU + int8")
                device = "cpu"
                compute_type = "int8"
        except ImportError:
            device = "cpu"
            compute_type = "int8"

        print(
            f"[transcriber] Loading faster-whisper '{self.config.model}' "
            f"on {device} ({compute_type})..."
        )
        started_at = time.time()
        self._model = WhisperModel(
            self.config.model,
            device=device,
            compute_type=compute_type,
        )
        print(f"[transcriber] Model loaded in {time.time() - started_at:.1f}s")

    def transcribe(
        self,
        audio: np.ndarray,
        start_ms: int,
        end_ms: int,
        seg_id: int,
    ) -> Optional[TranscriptSegment]:
        if self._model is None or len(audio) == 0:
            return None

        started_at = time.time()
        kwargs = {
            "beam_size": self.config.beam_size,
            "vad_filter": self.config.vad_filter,
            "no_speech_threshold": self.config.no_speech_threshold,
            "log_prob_threshold": self.config.log_prob_threshold,
            "compression_ratio_threshold": self.config.compression_ratio_threshold,
            "condition_on_previous_text": False,
        }
        if self.config.language:
            kwargs["language"] = self.config.language
        if self.config.initial_prompt:
            kwargs["initial_prompt"] = self.config.initial_prompt

        try:
            segments_gen, info = self._model.transcribe(audio, **kwargs)
            text = " ".join(seg.text.strip() for seg in segments_gen).strip()
        except Exception as exc:
            print(f"[transcriber] L\u1ed7i transcribe: {exc}")
            return None

        latency_ms = int((time.time() - started_at) * 1000)
        if not text:
            return None

        if is_hallucination(text, self.config.hallucination_blocklist):
            print(f"[transcriber] Skipped hallucination: {text}")
            from utils.hallucination_log import log_hallucination
            log_hallucination(text, source=self.config.engine)
            return None

        if self._last_text and text.lower() == self._last_text.lower():
            print(f"[transcriber] Ignored duplicate local text: {text}")
            return None
        self._last_text = text

        return TranscriptSegment(
            id=seg_id,
            text=text,
            language=info.language,
            start_ms=start_ms,
            end_ms=end_ms,
            duration_ms=end_ms - start_ms,
            engine_latency_ms=latency_ms,
        )

    def close(self) -> None:
        self._model = None


class OpenAIWhisperTranscriber(BaseTranscriber):
    def __init__(self, config: STTConfig):
        from openai import OpenAI

        self.config = config
        self._client = OpenAI(
            api_key=config.api_key,
            base_url=config.api_base,
        )
        self._last_text = ""

    def transcribe(
        self,
        audio: np.ndarray,
        start_ms: int,
        end_ms: int,
        seg_id: int,
    ) -> Optional[TranscriptSegment]:
        if len(audio) == 0:
            return None

        started_at = time.time()
        wav_bytes = self._to_wav_bytes(audio)
        language = self.config.language or "auto"
        text = ""

        try:
            kwargs = {
                "model": self.config.api_model,
                "file": ("audio.wav", wav_bytes, "audio/wav"),
                "response_format": "verbose_json",
            }
            if self.config.language:
                kwargs["language"] = self.config.language

            response = self._client.audio.transcriptions.create(**kwargs)
            if isinstance(response, str):
                text = response.strip()
            else:
                text = getattr(response, "text", None)
                language = getattr(response, "language", None) or language
                if text is None and isinstance(response, dict):
                    text = response.get("text")
                    language = response.get("language") or language
                text = str(text).strip() if text is not None else ""
        except Exception as exc:
            print(f"[transcriber] verbose_json failed, retrying text response: {exc}")
            try:
                fallback_kwargs = {
                    "model": self.config.api_model,
                    "file": ("audio.wav", wav_bytes, "audio/wav"),
                    "response_format": "text",
                }
                if self.config.language:
                    fallback_kwargs["language"] = self.config.language
                response = self._client.audio.transcriptions.create(**fallback_kwargs)
                text = response.strip() if isinstance(response, str) else str(response).strip()
            except Exception as fallback_exc:
                print(f"[transcriber] API error: {fallback_exc}")
                return None

        latency_ms = int((time.time() - started_at) * 1000)
        if not text:
            return None

        if is_hallucination(text, self.config.hallucination_blocklist):
            print(f"[transcriber] Skipped hallucination: {text}")
            from utils.hallucination_log import log_hallucination
            log_hallucination(text, source=self.config.engine)
            return None

        if text.lower() == self._last_text.lower():
            print(f"[transcriber] Ignored duplicate api text: {text}")
            return None
        self._last_text = text

        return TranscriptSegment(
            id=seg_id,
            text=text,
            language=language,
            start_ms=start_ms,
            end_ms=end_ms,
            duration_ms=end_ms - start_ms,
            engine_latency_ms=latency_ms,
        )

    @staticmethod
    def _to_wav_bytes(audio: np.ndarray, sample_rate: int = 16000) -> bytes:
        pcm = (audio * 32767).astype(np.int16)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm.tobytes())
        return buffer.getvalue()

    def close(self) -> None:
        self._client.close()


def create_transcriber(config: STTConfig) -> BaseTranscriber:
    if config.engine == "faster-whisper":
        return FasterWhisperTranscriber(config)
    if config.engine == "openai-api":
        return OpenAIWhisperTranscriber(config)
    raise ValueError(f"Unsupported STT engine: {config.engine}")
