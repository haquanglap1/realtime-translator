"""
Audio capture from microphone and/or system audio (loopback).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

try:
    import pyaudiowpatch as pyaudio

    HAS_PYAUDIO_WPATCH = True
except ImportError:
    HAS_PYAUDIO_WPATCH = False

from utils.config import AudioConfig
from utils.ring_buffer import RingBuffer


@dataclass
class AudioChunk:
    audio: np.ndarray
    source_label: str
    speaker_label: str


def list_devices() -> list[dict]:
    devices = []
    for index, dev in enumerate(sd.query_devices()):
        devices.append(
            {
                "index": index,
                "name": dev["name"],
                "hostapi": sd.query_hostapis(dev["hostapi"])["name"],
                "max_input": dev["max_input_channels"],
                "max_output": dev["max_output_channels"],
                "default_sr": dev["default_samplerate"],
            }
        )
    return devices


def find_loopback_device() -> Optional[dict]:
    loopback_keywords = ["stereo mix", "loopback", "what u hear", "wave out"]
    all_devices = sd.query_devices()
    hostapis = sd.query_hostapis()

    api_priority = {
        "Windows WASAPI": 0,
        "Windows WDM-KS": 1,
        "Windows DirectSound": 2,
        "MME": 3,
    }

    candidates = []
    for index, dev in enumerate(all_devices):
        if dev["max_input_channels"] <= 0:
            continue
        name_lower = dev["name"].lower()
        if not any(keyword in name_lower for keyword in loopback_keywords):
            continue

        hostapi_name = hostapis[dev["hostapi"]]["name"]
        candidates.append(
            (
                api_priority.get(hostapi_name, 99),
                index,
                {
                    "index": index,
                    "samplerate": dev["default_samplerate"],
                    "channels": min(dev["max_input_channels"], 2),
                    "name": dev["name"],
                    "method": "stereo-mix",
                    "hostapi": hostapi_name,
                },
            )
        )

    if candidates:
        candidates.sort(key=lambda item: item[:2])
        return candidates[0][2]
    return None


def find_default_mic_device() -> Optional[dict]:
    all_devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    loopback_keywords = ["stereo mix", "loopback", "what u hear", "wave out"]

    def _is_loopback(name: str) -> bool:
        return any(keyword in name.lower() for keyword in loopback_keywords)

    preferred_apis = [
        "MME",
        "Windows DirectSound",
        "Windows WASAPI",
        "Windows WDM-KS",
    ]

    for api_name in preferred_apis:
        api_idx = None
        for index, api in enumerate(hostapis):
            if api_name in api["name"]:
                api_idx = index
                break
        if api_idx is None:
            continue

        default_in = hostapis[api_idx].get("default_input_device", -1)
        if default_in >= 0:
            dev = all_devices[default_in]
            if dev["max_input_channels"] > 0 and not _is_loopback(dev["name"]):
                return {
                    "index": default_in,
                    "samplerate": dev["default_samplerate"],
                    "channels": min(dev["max_input_channels"], 2),
                    "name": dev["name"],
                }

        for index, dev in enumerate(all_devices):
            if dev["hostapi"] == api_idx and dev["max_input_channels"] > 0:
                if not _is_loopback(dev["name"]):
                    return {
                        "index": index,
                        "samplerate": dev["default_samplerate"],
                        "channels": min(dev["max_input_channels"], 2),
                        "name": dev["name"],
                    }

    return None


def _resample_linear(audio: np.ndarray, from_sr: float, to_sr: int) -> np.ndarray:
    if int(from_sr) == to_sr:
        return audio
    ratio = to_sr / from_sr
    new_len = int(len(audio) * ratio)
    indices = np.linspace(0, len(audio) - 1, new_len)
    return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)


class AudioCapture:
    def __init__(self, config: AudioConfig, on_loopback_missing: Optional[Callable] = None):
        self.config = config
        self.buffer = RingBuffer(maxsize=300)
        self._streams: list[sd.InputStream] = []
        self._pa_streams = []
        self._pa_instance = None
        self._running = False
        self._lock = threading.Lock()
        self._on_loopback_missing = on_loopback_missing

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._open_streams()

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            for stream in self._streams:
                stream.stop()
                stream.close()
            self._streams.clear()

            for stream in self._pa_streams:
                stream.stop_stream()
                stream.close()
            self._pa_streams.clear()

            if self._pa_instance:
                self._pa_instance.terminate()
                self._pa_instance = None

    @property
    def is_running(self) -> bool:
        return self._running

    def _speaker_label_for_source(self, source_label: str) -> str:
        if self.config.source == "both":
            return "Speaker 1" if source_label == "mic" else "Speaker 2"
        return "Speaker 1"

    def _open_streams(self) -> None:
        source = self.config.source

        if source in ("loopback", "both"):
            self._open_loopback_stream()
        if source in ("mic", "both"):
            self._open_mic_stream()

        if not self._streams and not self._pa_streams:
            raise RuntimeError(
                f"Cannot open stream for source='{source}'. "
                "Check audio device settings. Run with --list-devices to see available devices."
            )

    def _make_callback(self, source_label: str, native_sr: float) -> Callable:
        target_sr = self.config.sample_rate
        needs_resample = int(native_sr) != target_sr
        speaker_label = self._speaker_label_for_source(source_label)

        def callback(indata: np.ndarray, _frames: int, _time_info, status):
            if status:
                print(f"[audio/{source_label}] {status}")
            mono = indata[:, 0].astype(np.float32)
            if needs_resample:
                mono = _resample_linear(mono, native_sr, target_sr)
            self.buffer.put(
                AudioChunk(
                    audio=mono,
                    source_label=source_label,
                    speaker_label=speaker_label,
                )
            )

        return callback

    def _make_pyaudio_callback(
        self,
        source_label: str,
        native_sr: float,
        channels: int,
    ) -> Callable:
        target_sr = self.config.sample_rate
        needs_resample = int(native_sr) != target_sr
        speaker_label = self._speaker_label_for_source(source_label)

        def callback(in_data, _frame_count, _time_info, _status):
            try:
                indata = np.frombuffer(in_data, dtype=np.float32)
                if channels > 1:
                    indata = indata.reshape(-1, channels)
                    mono = indata[:, 0]
                else:
                    mono = indata

                if needs_resample:
                    mono = _resample_linear(mono, native_sr, target_sr)
                self.buffer.put(
                    AudioChunk(
                        audio=mono,
                        source_label=source_label,
                        speaker_label=speaker_label,
                    )
                )
            except Exception as exc:
                print(f"[audio/{source_label}] callback error: {exc}")
            import pyaudiowpatch as pyaudio_mod

            return (in_data, pyaudio_mod.paContinue)

        return callback

    def _open_loopback_stream(self) -> None:
        if HAS_PYAUDIO_WPATCH and self.config.device_index is None:
            if not self._pa_instance:
                self._pa_instance = pyaudio.PyAudio()

            try:
                wasapi_info = self._pa_instance.get_host_api_info_by_type(
                    pyaudio.paWASAPI
                )
                default_speakers = self._pa_instance.get_device_info_by_index(
                    wasapi_info["defaultOutputDevice"]
                )

                if not default_speakers["isLoopbackDevice"]:
                    for loopback in self._pa_instance.get_loopback_device_info_generator():
                        if default_speakers["name"] in loopback["name"]:
                            default_speakers = loopback
                            break

                native_sr = int(default_speakers["defaultSampleRate"])
                native_ch = default_speakers["maxInputChannels"]
                blocksize = int(self.config.blocksize * native_sr / self.config.sample_rate)

                stream = self._pa_instance.open(
                    format=pyaudio.paFloat32,
                    channels=native_ch,
                    rate=native_sr,
                    frames_per_buffer=blocksize,
                    input=True,
                    input_device_index=default_speakers["index"],
                    stream_callback=self._make_pyaudio_callback(
                        "loopback",
                        native_sr,
                        native_ch,
                    ),
                )
                stream.start_stream()
                self._pa_streams.append(stream)

                resample_note = ""
                if int(native_sr) != self.config.sample_rate:
                    resample_note = f", resample {int(native_sr)}->{self.config.sample_rate}Hz"
                print(
                    f"[audio] Loopback (PyAudioWPatch): {default_speakers['name']} "
                    f"({int(native_sr)}Hz{resample_note})"
                )
                return
            except Exception as exc:
                print(
                    f"[audio] PyAudioWPatch loopback setup failed: {exc}. "
                    "Falling back to sounddevice."
                )

        if self.config.device_index is not None:
            dev = sd.query_devices(self.config.device_index)
            device_info = {
                "index": self.config.device_index,
                "samplerate": dev["default_samplerate"],
                "channels": min(dev["max_input_channels"], 2) or 1,
                "name": dev["name"],
                "method": "manual",
            }
        else:
            device_info = find_loopback_device()

        if device_info is None:
            print("[audio] No loopback device found (Stereo Mix disabled?).")
            if self._on_loopback_missing:
                self._on_loopback_missing()
            return

        native_sr = device_info["samplerate"]
        native_ch = device_info["channels"]
        blocksize = int(self.config.blocksize * native_sr / self.config.sample_rate)

        try:
            stream = sd.InputStream(
                device=device_info["index"],
                samplerate=native_sr,
                channels=native_ch,
                dtype="float32",
                blocksize=blocksize,
                callback=self._make_callback("loopback", native_sr),
            )
            stream.start()
            self._streams.append(stream)
            resample_note = ""
            if int(native_sr) != self.config.sample_rate:
                resample_note = f", resample {int(native_sr)}->{self.config.sample_rate}Hz"
            print(
                f"[audio] Loopback: {device_info['name']} "
                f"[{device_info.get('hostapi', device_info.get('method', 'unknown'))}] "
                f"({int(native_sr)}Hz{resample_note})"
            )
        except Exception as exc:
            print(f"[audio] Failed to open loopback stream: {exc}")

    def _open_mic_stream(self) -> None:
        if self.config.device_index is not None and self.config.source == "mic":
            dev = sd.query_devices(self.config.device_index)
            device_info = {
                "index": self.config.device_index,
                "samplerate": dev["default_samplerate"],
                "channels": min(dev["max_input_channels"], 2) or 1,
                "name": dev["name"],
            }
        else:
            device_info = find_default_mic_device()

        if device_info is None:
            print("[audio] No microphone found. Skipping mic stream.")
            return

        native_sr = device_info["samplerate"]
        native_ch = device_info["channels"]
        blocksize = int(self.config.blocksize * native_sr / self.config.sample_rate)

        try:
            stream = sd.InputStream(
                device=device_info["index"],
                samplerate=native_sr,
                channels=native_ch,
                dtype="float32",
                blocksize=blocksize,
                callback=self._make_callback("mic", native_sr),
            )
            stream.start()
            self._streams.append(stream)
            resample_note = ""
            if int(native_sr) != self.config.sample_rate:
                resample_note = f", resample {int(native_sr)}->{self.config.sample_rate}Hz"
            print(f"[audio] Mic: {device_info['name']} ({int(native_sr)}Hz{resample_note})")
        except Exception as exc:
            print(f"[audio] Failed to open mic stream: {exc}")
