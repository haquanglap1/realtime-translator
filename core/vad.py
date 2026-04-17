"""
Voice Activity Detection (VAD) using a simple energy-based algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from utils.config import VADConfig


@dataclass
class SpeechSegment:
    audio: np.ndarray
    start_ms: int
    end_ms: int
    duration_ms: int
    source_label: str = ""
    speaker_label: str = ""


def segment_quality_check(
    segment: "SpeechSegment",
    *,
    sample_rate: int,
    frame_ms: int,
    min_duration_ms: int,
    min_rms: float,
    min_active_ratio: float,
    frame_threshold: float,
) -> tuple[bool, str]:
    """Second-stage gate — kiểm tra SpeechSegment có đủ chất lượng để gửi transcribe.

    Trả (passes, reason). Nếu passes=False, reason mô tả ngắn gọn lý do.
    """
    if segment.duration_ms < min_duration_ms:
        return False, f"duration={segment.duration_ms}ms<{min_duration_ms}"

    audio = segment.audio
    if audio is None or len(audio) == 0:
        return False, "empty audio"

    overall_rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))
    if overall_rms < min_rms:
        return False, f"rms={overall_rms:.4f}<{min_rms}"

    frame_size = max(1, int(sample_rate * frame_ms / 1000))
    total_frames = 0
    active_frames = 0
    for start in range(0, len(audio) - frame_size + 1, frame_size):
        frame = audio[start : start + frame_size]
        frame_rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
        total_frames += 1
        if frame_rms > frame_threshold:
            active_frames += 1

    if total_frames == 0:
        return False, "no frames"

    ratio = active_frames / total_frames
    if ratio < min_active_ratio:
        return False, f"active_ratio={ratio:.2f}<{min_active_ratio}"

    return True, "ok"


class EnergyVAD:
    def __init__(self, config: VADConfig, sample_rate: int = 16000):
        self.config = config
        self.sample_rate = sample_rate
        self.frame_size = int(sample_rate * config.frame_ms / 1000)

        self._speech_frames: list[np.ndarray] = []
        self._in_speech = False
        self._speech_count = 0
        self._silence_count = 0
        self._session_ms = 0
        self._segment_start_ms = 0

    def process(
        self,
        chunk: np.ndarray,
        *,
        source_label: str = "",
        speaker_label: str = "",
    ) -> list[SpeechSegment]:
        results: list[SpeechSegment] = []
        cfg = self.config

        for index in range(0, len(chunk) - self.frame_size + 1, self.frame_size):
            frame = chunk[index : index + self.frame_size]
            frame_ms = int(self.frame_size / self.sample_rate * 1000)
            is_speech = self._rms(frame) > cfg.speech_threshold

            if is_speech:
                if not self._in_speech:
                    self._in_speech = True
                    self._speech_count = 0
                    self._silence_count = 0
                    self._segment_start_ms = self._session_ms

                self._speech_frames.append(frame)
                self._speech_count += 1
                self._silence_count = 0

                if self._speech_count >= cfg.max_speech_frames:
                    seg = self._emit_segment(
                        source_label=source_label,
                        speaker_label=speaker_label,
                    )
                    if seg is not None:
                        results.append(seg)
            else:
                if self._in_speech:
                    self._speech_frames.append(frame)
                    self._silence_count += 1

                    if self._silence_count >= cfg.silence_frames_to_end:
                        seg = self._emit_segment(
                            trim_silence=True,
                            source_label=source_label,
                            speaker_label=speaker_label,
                        )
                        if seg is not None:
                            results.append(seg)

            self._session_ms += frame_ms

        return results

    def flush(self, *, source_label: str = "", speaker_label: str = "") -> list[SpeechSegment]:
        results = []
        if self._in_speech and self._speech_count >= self.config.min_speech_frames:
            seg = self._emit_segment(
                trim_silence=True,
                source_label=source_label,
                speaker_label=speaker_label,
            )
            if seg is not None:
                results.append(seg)
        return results

    def reset(self) -> None:
        self._speech_frames.clear()
        self._in_speech = False
        self._speech_count = 0
        self._silence_count = 0
        self._session_ms = 0
        self._segment_start_ms = 0

    @staticmethod
    def _rms(frame: np.ndarray) -> float:
        return float(np.sqrt(np.mean(frame**2)))

    def _emit_segment(
        self,
        trim_silence: bool = False,
        *,
        source_label: str = "",
        speaker_label: str = "",
    ) -> SpeechSegment | None:
        if self._speech_count < self.config.min_speech_frames:
            self._reset_state()
            return None

        frames = self._speech_frames.copy()

        if trim_silence and self._silence_count > 0:
            trim = max(0, len(frames) - self._silence_count)
            frames = frames[:trim]

        if not frames:
            self._reset_state()
            return None

        audio = np.concatenate(frames)
        duration_ms = int(len(audio) / self.sample_rate * 1000)
        end_ms = self._segment_start_ms + duration_ms

        seg = SpeechSegment(
            audio=audio,
            start_ms=self._segment_start_ms,
            end_ms=end_ms,
            duration_ms=duration_ms,
            source_label=source_label,
            speaker_label=speaker_label,
        )

        self._reset_state()
        return seg

    def _reset_state(self) -> None:
        self._speech_frames.clear()
        self._in_speech = False
        self._speech_count = 0
        self._silence_count = 0
