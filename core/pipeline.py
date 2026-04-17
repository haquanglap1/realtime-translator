"""
Main processing pipeline: Audio -> VAD -> Whisper -> [LLM Translation] -> UI.

Thread model:
  Thread 1 (sounddevice internal): audio callback -> AudioCapture.buffer
  Thread 2 (_vad_thread):          buffer -> VAD -> speech_queue
  Thread 3 (_transcriber_thread):  speech_queue -> Whisper -> on_result callback
  Thread 4 (_diarizer_thread):     transcript -> pyannote -> speaker updates
  Thread 5 (_translator_thread):   translation_queue -> LLM -> on_translation callback
  Thread 6 (main/Qt):              signals update UI
"""

from __future__ import annotations

import concurrent.futures
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from core.audio_capture import AudioCapture, AudioChunk
from core.diarizer import BaseDiarizer, DiarizedTurn, create_diarizer
from core.transcriber import BaseTranscriber, TranscriptSegment, create_transcriber
from core.translator import Translator
from core.vad import EnergyVAD, SpeechSegment, segment_quality_check
from utils.config import AppConfig
from utils.silero_vad import SileroVADGate


LANGUAGE_NAME_MAP = {
    "vi": "vietnamese",
    "en": "english",
    "zh": "chinese",
    "ja": "japanese",
    "ko": "korean",
    "fr": "french",
    "de": "german",
    "es": "spanish",
    "pt": "portuguese",
    "ru": "russian",
    "th": "thai",
    "id": "indonesian",
    "ms": "malay",
    "ar": "arabic",
    "hi": "hindi",
    "it": "italian",
    "nl": "dutch",
    "pl": "polish",
    "tr": "turkish",
    "uk": "ukrainian",
    "cs": "czech",
    "ro": "romanian",
    "el": "greek",
    "hu": "hungarian",
    "sv": "swedish",
    "da": "danish",
    "fi": "finnish",
    "no": "norwegian",
}


@dataclass
class TimedAudioChunk:
    audio: np.ndarray
    start_ms: int
    end_ms: int


@dataclass
class SpeakerTurnRecord:
    start_ms: int
    end_ms: int
    speaker_label: str


class Pipeline:
    def __init__(
        self,
        config: AppConfig,
        on_result: Callable[[TranscriptSegment], None],
        on_translation: Optional[Callable[[list[TranscriptSegment]], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_rewrite_state_changed: Optional[Callable[[bool], None]] = None,
    ):
        self.config = config
        self.on_result = on_result
        self.on_translation = on_translation or (lambda s: None)
        self.on_status = on_status or (lambda s: None)
        self.on_rewrite_state_changed = on_rewrite_state_changed or (lambda s: None)

        self._capture = AudioCapture(config.audio)
        self._vads: dict[str, EnergyVAD] = {}
        self._transcriber: Optional[BaseTranscriber] = None
        self._translator: Optional[Translator] = None
        self._diarizer: Optional[BaseDiarizer] = None
        self._silero: Optional[SileroVADGate] = None

        self._speech_queue: queue.Queue[SpeechSegment | None] = queue.Queue(maxsize=20)
        self._diarization_queue: queue.Queue[TranscriptSegment | None] = queue.Queue(maxsize=50)
        self._translation_queue: queue.Queue[TranscriptSegment | None] = queue.Queue(maxsize=50)

        self._vad_thread: Optional[threading.Thread] = None
        self._transcriber_thread: Optional[threading.Thread] = None
        self._diarizer_thread: Optional[threading.Thread] = None
        self._translator_thread: Optional[threading.Thread] = None
        self._rewrite_thread: Optional[threading.Thread] = None

        self._running = False
        self._seg_counter = 0
        self._rewrite_lock = threading.Lock()
        self._session_token = 0

        self._history_lock = threading.Lock()
        self._source_audio_history: dict[str, deque[TimedAudioChunk]] = {}
        self._source_audio_clock_ms: dict[str, int] = {}
        self._speaker_turn_history: dict[str, deque[SpeakerTurnRecord]] = {}
        self._speaker_label_counter: dict[str, int] = {}

    def start(self) -> None:
        if self._running:
            return
        try:
            self.on_status("Loading Whisper model...")
            self._transcriber = create_transcriber(self.config.stt)

            if self.config.vad.use_silero_vad and self._silero is None:
                self.on_status("Loading Silero VAD...")
                self._silero = SileroVADGate(
                    threshold=self.config.vad.silero_speech_prob,
                )
                if not self._silero.available:
                    print(
                        "[pipeline] Silero VAD không khả dụng — tiếp tục mà không dùng."
                    )

            if self._use_pyannote_strategy():
                self.on_status("Loading speaker diarization...")
                self._diarizer = create_diarizer(self.config.diarization)

            if self.config.llm.enabled:
                self.on_status("Connecting to LLM...")
                self._translator = Translator(self.config.llm)

            self._running = True
            self._session_token += 1
            self._vads = {}
            self._reset_runtime_state()

            self._vad_thread = threading.Thread(
                target=self._vad_loop,
                name="vad-thread",
                daemon=True,
            )
            self._transcriber_thread = threading.Thread(
                target=self._transcriber_loop,
                name="transcriber-thread",
                daemon=True,
            )
            self._vad_thread.start()
            self._transcriber_thread.start()

            if self._use_pyannote_strategy():
                self._diarizer_thread = threading.Thread(
                    target=self._diarizer_loop,
                    name="diarizer-thread",
                    daemon=True,
                )
                self._diarizer_thread.start()

            if self._translator:
                self._translator_thread = threading.Thread(
                    target=self._translator_loop,
                    name="translator-thread",
                    daemon=True,
                )
                self._translator_thread.start()

            self._capture.start()
            self.on_status("Listening...")
        except Exception:
            self._abort_startup()
            raise

    def stop(self) -> None:
        if not self._running:
            return

        self._capture.stop()
        self._running = False
        self._session_token += 1

        for source_label, vad in self._vads.items():
            speaker_label = "Speaker 2" if (
                self.config.audio.source == "both" and source_label == "loopback"
            ) else "Speaker 1"
            remaining = vad.flush(
                source_label=source_label,
                speaker_label=speaker_label,
            )
            for seg in remaining:
                try:
                    self._speech_queue.put_nowait(seg)
                except queue.Full:
                    pass

        self._speech_queue.put(None)
        self._diarization_queue.put(None)
        self._translation_queue.put(None)

        if self._vad_thread:
            self._vad_thread.join(timeout=2.0)
        if self._transcriber_thread:
            self._transcriber_thread.join(timeout=10.0)
        if self._diarizer_thread:
            self._diarizer_thread.join(timeout=10.0)
        if self._translator_thread:
            self._translator_thread.join(timeout=5.0)

        if self._transcriber:
            self._transcriber.close()
        if self._translator:
            self._translator.close()
        if self._diarizer:
            self._diarizer.close()

        self._translator = None
        self._transcriber = None
        self._diarizer = None
        self._vads = {}
        self._vad_thread = None
        self._transcriber_thread = None
        self._diarizer_thread = None
        self._translator_thread = None
        self._speech_queue = queue.Queue(maxsize=20)
        self._diarization_queue = queue.Queue(maxsize=50)
        self._translation_queue = queue.Queue(maxsize=50)
        self._reset_runtime_state()

        self.on_status("Stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def can_rewrite(self) -> bool:
        return self.config.llm.enabled

    @property
    def is_rewriting(self) -> bool:
        return self._rewrite_thread is not None and self._rewrite_thread.is_alive()

    def rewrite_latest_transcript(self, segments: list[TranscriptSegment]) -> None:
        if not self.config.llm.enabled:
            raise RuntimeError("LLM translation is disabled.")
        if not segments:
            raise ValueError("No transcript available to rewrite.")

        with self._rewrite_lock:
            if self.is_rewriting:
                raise RuntimeError("A rewrite is already in progress.")

            snapshot = [
                TranscriptSegment(
                    id=segment.id,
                    text=segment.text,
                    language=segment.language,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    duration_ms=segment.duration_ms,
                    engine_latency_ms=segment.engine_latency_ms,
                    speaker_label=segment.speaker_label,
                    source_label=segment.source_label,
                    translated=segment.translated,
                )
                for segment in segments
                if segment.text.strip()
            ]
            if not snapshot:
                raise ValueError("No transcript text available to rewrite.")

            self._rewrite_thread = threading.Thread(
                target=self._rewrite_worker,
                args=(snapshot,),
                name="rewrite-thread",
                daemon=True,
            )
            self._rewrite_thread.start()

    def _use_pyannote_strategy(self) -> bool:
        return (
            self.config.audio.speaker_strategy == "pyannote"
            and self.config.audio.source != "both"
            and self.config.diarization.enabled
        )

    def _reset_runtime_state(self) -> None:
        with self._history_lock:
            self._source_audio_history = {}
            self._source_audio_clock_ms = {}
            self._speaker_turn_history = {}
            self._speaker_label_counter = {}

    def _abort_startup(self) -> None:
        self._capture.stop()
        self._running = False
        self._vads = {}

        self._speech_queue.put(None)
        self._diarization_queue.put(None)
        self._translation_queue.put(None)

        if self._vad_thread and self._vad_thread.is_alive():
            self._vad_thread.join(timeout=1.0)
        if self._transcriber_thread and self._transcriber_thread.is_alive():
            self._transcriber_thread.join(timeout=1.0)
        if self._diarizer_thread and self._diarizer_thread.is_alive():
            self._diarizer_thread.join(timeout=1.0)
        if self._translator_thread and self._translator_thread.is_alive():
            self._translator_thread.join(timeout=1.0)

        if self._transcriber:
            self._transcriber.close()
        if self._translator:
            self._translator.close()
        if self._diarizer:
            self._diarizer.close()

        self._transcriber = None
        self._translator = None
        self._diarizer = None
        self._vad_thread = None
        self._transcriber_thread = None
        self._diarizer_thread = None
        self._translator_thread = None
        self._speech_queue = queue.Queue(maxsize=20)
        self._diarization_queue = queue.Queue(maxsize=50)
        self._translation_queue = queue.Queue(maxsize=50)
        self._reset_runtime_state()
        self.on_status("Start failed")

    def _rewrite_worker(self, segments: list[TranscriptSegment]) -> None:
        translator: Optional[Translator] = None
        self.on_rewrite_state_changed(True)
        self.on_status("Rewriting latest transcript...")

        try:
            translator = Translator(self.config.llm)
            rewritten_lines = translator.rewrite_transcript(
                [self._format_segment_for_translation(segment) for segment in segments]
            )
            if not rewritten_lines:
                self.on_status("Rewrite failed")
                return

            for segment, translated_text in zip(segments, rewritten_lines):
                segment.translated = translated_text

            save_path = self._save_rewrite_translation(rewritten_lines)
            self.on_translation(segments)
            if save_path is not None:
                self.on_status("Rewrite completed and saved")
            else:
                self.on_status("Rewrite completed")
        except Exception as exc:
            print(f"[pipeline] rewrite error: {exc}")
            self.on_status("Rewrite failed")
        finally:
            if translator is not None:
                translator.close()
            self.on_rewrite_state_changed(False)
            with self._rewrite_lock:
                self._rewrite_thread = None

    def _resolve_transcript_dir(self) -> Path:
        configured_dir = (self.config.llm.transcript_save_dir or "").strip()
        if configured_dir:
            path = Path(configured_dir).expanduser()
            if path.is_dir():
                return path
        return Path.cwd()

    def _save_rewrite_translation(self, lines: list[str]) -> Optional[Path]:
        clean_lines = [line.strip() for line in lines if line.strip()]
        if not clean_lines:
            return None

        save_dir = self._resolve_transcript_dir()
        save_dir.mkdir(parents=True, exist_ok=True)
        filename = f"transcript_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_translate.txt"
        file_path = save_dir / filename

        try:
            file_path.write_text("\n".join(clean_lines) + "\n", encoding="utf-8")
            print(f"[pipeline] Saved rewritten translation to: {file_path}")
            return file_path
        except Exception as exc:
            print(f"[pipeline] Failed to save rewritten translation: {exc}")
            return None

    def _record_audio_chunk(self, chunk: AudioChunk) -> None:
        duration_ms = int(len(chunk.audio) / self.config.audio.sample_rate * 1000)
        if duration_ms <= 0:
            return

        with self._history_lock:
            source_label = chunk.source_label
            start_ms = self._source_audio_clock_ms.get(source_label, 0)
            end_ms = start_ms + duration_ms
            self._source_audio_clock_ms[source_label] = end_ms

            history = self._source_audio_history.setdefault(source_label, deque())
            history.append(
                TimedAudioChunk(
                    audio=chunk.audio.copy(),
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
            )

            cutoff_ms = end_ms - max(self.config.diarization.window_ms * 3, 30000)
            while history and history[0].end_ms < cutoff_ms:
                history.popleft()

    def _slice_audio_window(
        self,
        source_label: str,
        segment_end_ms: int,
    ) -> tuple[np.ndarray, int] | None:
        window_ms = max(2000, self.config.diarization.window_ms)
        window_start_ms = max(0, segment_end_ms - window_ms)

        with self._history_lock:
            chunks = list(self._source_audio_history.get(source_label, ()))

        if not chunks:
            return None

        pieces: list[np.ndarray] = []
        for chunk in chunks:
            overlap_start = max(window_start_ms, chunk.start_ms)
            overlap_end = min(segment_end_ms, chunk.end_ms)
            if overlap_end <= overlap_start:
                continue

            chunk_span_ms = max(1, chunk.end_ms - chunk.start_ms)
            start_ratio = (overlap_start - chunk.start_ms) / chunk_span_ms
            end_ratio = (overlap_end - chunk.start_ms) / chunk_span_ms
            start_idx = max(0, int(start_ratio * len(chunk.audio)))
            end_idx = min(len(chunk.audio), int(np.ceil(end_ratio * len(chunk.audio))))
            if end_idx > start_idx:
                pieces.append(chunk.audio[start_idx:end_idx])

        if not pieces:
            return None

        return np.concatenate(pieces).astype(np.float32), window_start_ms

    def _effective_max_speakers(self) -> int:
        if self.config.diarization.num_speakers > 0:
            return self.config.diarization.num_speakers
        return max(1, self.config.diarization.max_speakers)

    def _next_speaker_label(self, source_label: str) -> str:
        max_spk = self._effective_max_speakers()
        current_count = self._speaker_label_counter.get(source_label, 0)
        if current_count >= max_spk:
            # Cap reached — return the highest allowed label as fallback.
            # The caller (_reconcile_speaker_turns) will pick a better match
            # from used_labels when possible.
            return f"Speaker {max_spk}"
        next_index = current_count + 1
        self._speaker_label_counter[source_label] = next_index
        return f"Speaker {next_index}"

    @staticmethod
    def _overlap_ms(start_a: int, end_a: int, start_b: int, end_b: int) -> int:
        return max(0, min(end_a, end_b) - max(start_a, start_b))

    def _reconcile_speaker_turns(
        self,
        source_label: str,
        turns: list[SpeakerTurnRecord],
    ) -> list[SpeakerTurnRecord]:
        if not turns:
            return []

        with self._history_lock:
            history = self._speaker_turn_history.setdefault(source_label, deque())
            raw_speakers = sorted({turn.speaker_label for turn in turns})
            speaker_map: dict[str, str] = {}
            used_labels: set[str] = set()

            for raw_speaker in raw_speakers:
                speaker_turns = [turn for turn in turns if turn.speaker_label == raw_speaker]
                overlap_scores: dict[str, int] = {}
                for turn in speaker_turns:
                    for past_turn in history:
                        overlap = self._overlap_ms(
                            turn.start_ms,
                            turn.end_ms,
                            past_turn.start_ms,
                            past_turn.end_ms,
                        )
                        if overlap > 0:
                            overlap_scores[past_turn.speaker_label] = (
                                overlap_scores.get(past_turn.speaker_label, 0) + overlap
                            )

                ranked = sorted(
                    overlap_scores.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
                chosen_label = next(
                    (label for label, score in ranked if score > 0 and label not in used_labels),
                    None,
                )
                if chosen_label is None:
                    max_spk = self._effective_max_speakers()
                    current_count = self._speaker_label_counter.get(source_label, 0)
                    if current_count >= max_spk:
                        # Cap reached: pick the existing label not yet used in
                        # this batch that was least recently active in history.
                        all_labels = {f"Speaker {i}" for i in range(1, max_spk + 1)}
                        available = all_labels - used_labels
                        if available:
                            # Pick the one whose last activity in history is oldest
                            def _last_active(lbl: str) -> int:
                                for past in reversed(history):
                                    if past.speaker_label == lbl:
                                        return past.end_ms
                                return -1
                            chosen_label = min(available, key=_last_active)
                        else:
                            # All labels used in this batch already, just reuse last
                            chosen_label = f"Speaker {max_spk}"
                    else:
                        chosen_label = self._next_speaker_label(source_label)

                used_labels.add(chosen_label)
                speaker_map[raw_speaker] = chosen_label

            resolved_turns = [
                SpeakerTurnRecord(
                    start_ms=turn.start_ms,
                    end_ms=turn.end_ms,
                    speaker_label=speaker_map.get(turn.speaker_label, turn.speaker_label),
                )
                for turn in turns
            ]

            for turn in resolved_turns:
                history.append(turn)

            cutoff_ms = resolved_turns[-1].end_ms - max(self.config.diarization.window_ms * 3, 30000)
            while history and history[0].end_ms < cutoff_ms:
                history.popleft()

        return resolved_turns

    def _select_speaker_label(
        self,
        turns: list[SpeakerTurnRecord],
        segment_start_ms: int,
        segment_end_ms: int,
        fallback_label: str,
    ) -> str:
        best_label = fallback_label
        best_overlap = -1
        for turn in turns:
            overlap = self._overlap_ms(
                turn.start_ms,
                turn.end_ms,
                segment_start_ms,
                segment_end_ms,
            )
            if overlap > best_overlap:
                best_overlap = overlap
                best_label = turn.speaker_label
        return best_label or "Speaker 1"

    def _format_segment_for_translation(self, segment: TranscriptSegment) -> str:
        speaker_label = (segment.speaker_label or "").strip()
        if speaker_label:
            return f"[{speaker_label}] {segment.text}"
        return segment.text

    def _queue_translation(self, segment: TranscriptSegment) -> None:
        if not self._translator or self._is_target_language(segment.language):
            return
        try:
            self._translation_queue.put_nowait(segment)
        except queue.Full:
            print("[pipeline] translation_queue full, skipping")

    def _vad_loop(self) -> None:
        while self._running:
            chunk_item = self._capture.buffer.get(timeout=0.1)
            if chunk_item is None:
                continue

            if isinstance(chunk_item, AudioChunk):
                chunk = chunk_item
            else:
                chunk = AudioChunk(
                    audio=chunk_item,
                    source_label="mixed",
                    speaker_label="Speaker 1",
                )

            self._record_audio_chunk(chunk)

            vad = self._vads.get(chunk.source_label)
            if vad is None:
                vad = EnergyVAD(self.config.vad, sample_rate=self.config.audio.sample_rate)
                self._vads[chunk.source_label] = vad

            segments = vad.process(
                chunk.audio,
                source_label=chunk.source_label,
                speaker_label=chunk.speaker_label,
            )
            for seg in segments:
                try:
                    self._speech_queue.put_nowait(seg)
                except queue.Full:
                    print("[pipeline] speech_queue full, dropping segment")

    def _is_target_language(self, language_code: str) -> bool:
        if not language_code:
            return False
        target = self.config.llm.target_language.lower().strip()
        detected = language_code.lower().strip()

        if detected == target:
            return True

        lang_name = LANGUAGE_NAME_MAP.get(detected, "")
        if lang_name and lang_name == target:
            return True

        if lang_name and (lang_name in target or target in lang_name):
            return True

        return False

    def _resolve_speaker_label(
        self,
        *,
        source_label: str,
        detected_language: str,
        fallback_label: str,
    ) -> str:
        strategy = (self.config.audio.speaker_strategy or "source").lower().strip()

        if strategy == "pyannote" and self.config.audio.source != "both":
            return fallback_label or "Detecting speaker..."

        if strategy == "language" and self.config.audio.source != "both":
            return "Speaker 2" if self._is_target_language(detected_language) else "Speaker 1"

        if self.config.audio.source == "both":
            return "Speaker 2" if source_label == "loopback" else "Speaker 1"

        return fallback_label or "Speaker 1"

    def _passes_quality_gate(self, seg: SpeechSegment) -> tuple[bool, str]:
        """Second-stage gate trước khi gọi STT để giảm hallucination.

        Chạy cho cả local + API. Áp dụng 2 lớp:
          - Energy-based: duration, RMS tổng thể, tỷ lệ frame active
          - Silero VAD (nếu bật): xác suất speech cao nhất
        """
        vad_cfg = self.config.vad

        passes, reason = segment_quality_check(
            seg,
            sample_rate=self.config.audio.sample_rate,
            frame_ms=vad_cfg.frame_ms,
            min_duration_ms=vad_cfg.min_segment_duration_ms,
            min_rms=vad_cfg.min_segment_rms,
            min_active_ratio=vad_cfg.min_active_ratio,
            frame_threshold=vad_cfg.speech_threshold,
        )
        if not passes:
            return False, reason

        if vad_cfg.use_silero_vad and self._silero is not None and self._silero.available:
            prob = self._silero.max_speech_prob(seg.audio)
            if prob < vad_cfg.silero_speech_prob:
                return False, f"silero={prob:.2f}<{vad_cfg.silero_speech_prob}"

        return True, "ok"

    def _transcriber_loop(self) -> None:
        while True:
            try:
                seg: SpeechSegment | None = self._speech_queue.get(timeout=0.5)
            except queue.Empty:
                if not self._running:
                    break
                continue

            if seg is None:
                break

            passes, reason = self._passes_quality_gate(seg)
            if not passes:
                print(
                    f"[pipeline] SKIP segment ({seg.duration_ms}ms, "
                    f"src={seg.source_label}) — {reason}"
                )
                continue

            self._seg_counter += 1
            result = self._transcriber.transcribe(
                audio=seg.audio,
                start_ms=seg.start_ms,
                end_ms=seg.end_ms,
                seg_id=self._seg_counter,
            )

            if result is None:
                continue

            result.source_label = seg.source_label
            is_target_lang = self._is_target_language(result.language)
            result.speaker_label = self._resolve_speaker_label(
                source_label=seg.source_label,
                detected_language=result.language,
                fallback_label=seg.speaker_label,
            )

            if is_target_lang:
                print(
                    f"[pipeline] #{result.id} [{result.language}] "
                    f"+{result.engine_latency_ms}ms | SKIP (target lang) | {result.text}"
                )
            else:
                print(
                    f"[pipeline] #{result.id} [{result.language}] "
                    f"+{result.engine_latency_ms}ms | {result.text}"
                )

            self.on_result(result)

            if self._use_pyannote_strategy() and self._diarizer is not None:
                try:
                    self._diarization_queue.put_nowait(result)
                except queue.Full:
                    print("[pipeline] diarization_queue full, skipping diarization")
                    self._queue_translation(result)
            else:
                self._queue_translation(result)

    def _diarizer_loop(self) -> None:
        while True:
            try:
                segment = self._diarization_queue.get(timeout=0.5)
            except queue.Empty:
                if not self._running:
                    break
                continue

            if segment is None:
                break

            try:
                window = self._slice_audio_window(segment.source_label, segment.end_ms)
                if window is not None and self._diarizer is not None:
                    audio_window, window_start_ms = window
                    diarized_turns = self._diarizer.diarize_window(
                        audio_window,
                        self.config.audio.sample_rate,
                    )
                    absolute_turns = [
                        SpeakerTurnRecord(
                            start_ms=window_start_ms + turn.start_ms,
                            end_ms=window_start_ms + turn.end_ms,
                            speaker_label=turn.speaker_id,
                        )
                        for turn in diarized_turns
                    ]
                    resolved_turns = self._reconcile_speaker_turns(
                        segment.source_label,
                        absolute_turns,
                    )
                    segment.speaker_label = self._select_speaker_label(
                        resolved_turns,
                        segment.start_ms,
                        segment.end_ms,
                        segment.speaker_label,
                    )
                self.on_translation([segment])
            except Exception as exc:
                print(f"[pipeline] diarization error: {exc}")
            finally:
                self._queue_translation(segment)

    def _translator_loop(self) -> None:
        session_token = self._session_token
        batch_segs: list[TranscriptSegment] = []
        batch_text: list[str] = []
        last_seg_time = time.time()
        idle_timeout = 0.5
        batch_size = max(1, self.config.llm.batch_size)
        context_queue = deque(maxlen=self.config.llm.context_segments)

        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, self.config.llm.thread_count)
        )

        def _do_translate(
            c_text: str,
            segments: list[TranscriptSegment],
            ctx: list[str],
        ) -> None:
            if not self._translator or session_token != self._session_token:
                return
            try:
                translated = self._translator.translate(c_text, context=ctx)
            except Exception as exc:
                print(f"[pipeline] thread error: {exc}")
                translated = None

            if translated and session_token == self._session_token:
                trans_lines = [line.strip() for line in translated.split("\n") if line.strip()]

                if len(trans_lines) == 1:
                    segments[-1].translated = trans_lines[0]
                    for seg_item in segments[:-1]:
                        seg_item.translated = ""
                else:
                    if len(trans_lines) >= len(segments):
                        lines_per_seg = len(trans_lines) / len(segments)
                        for index, seg_item in enumerate(segments):
                            start_idx = int(index * lines_per_seg)
                            end_idx = int((index + 1) * lines_per_seg)
                            seg_item.translated = "\n".join(trans_lines[start_idx:end_idx])
                    else:
                        offset = len(segments) - len(trans_lines)
                        for index, seg_item in enumerate(segments):
                            if index < offset:
                                seg_item.translated = ""
                            else:
                                seg_item.translated = trans_lines[index - offset]

                self.on_translation(segments)

        while True:
            wait_time = (
                max(0.1, idle_timeout - (time.time() - last_seg_time))
                if batch_segs
                else 0.5
            )
            try:
                seg: TranscriptSegment | None = self._translation_queue.get(timeout=wait_time)
            except queue.Empty:
                if not self._running:
                    break
                seg = None

            if seg is None and not batch_segs:
                if not self._running:
                    break
                continue

            if seg is not None:
                batch_segs.append(seg)
                batch_text.append(self._format_segment_for_translation(seg))
                last_seg_time = time.time()

            if not batch_segs:
                continue

            should_translate = False
            curr_text = "\n".join(batch_text).strip()
            elapsed_since_last = time.time() - last_seg_time
            batch_audio_duration_ms = batch_segs[-1].end_ms - batch_segs[0].start_ms

            if elapsed_since_last >= idle_timeout:
                should_translate = True
                print(f"[pipeline] translator flush: idle timeout ({elapsed_since_last:.1f}s)")
            elif len(batch_segs) >= batch_size:
                should_translate = True
                print(
                    f"[pipeline] translator flush: batch size reached "
                    f"({len(batch_segs)}/{batch_size})"
                )

            if should_translate:
                print(
                    f"[pipeline] translating batch: {len(batch_segs)} segs, "
                    f"{batch_audio_duration_ms}ms audio, {len(curr_text)} chars"
                )
                current_context = list(context_queue)
                executor.submit(_do_translate, curr_text, batch_segs, current_context)
                context_queue.append(curr_text)
                batch_segs = []
                batch_text = []

        executor.shutdown(wait=True, cancel_futures=True)
