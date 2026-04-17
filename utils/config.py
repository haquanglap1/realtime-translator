"""Load và quản lý cấu hình từ settings.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class AudioConfig:
    source: str = "loopback"          # "mic" | "loopback" | "both"
    speaker_strategy: str = "source"  # "source" | "language" | "pyannote"
    device_index: Optional[int] = None
    sample_rate: int = 16000
    channels: int = 1
    blocksize: int = 1600             # 100ms tại 16kHz


@dataclass
class VADConfig:
    # Lớp 1 — EnergyVAD gate (RMS-based, frame-level)
    speech_threshold: float = 0.025       # was 0.012 — nâng để loại noise nền văn phòng
    min_speech_frames: int = 15           # was 10 — loại segment < 450ms (Whisper hay ảo giác)
    silence_frames_to_end: int = 15
    max_speech_frames: int = 150
    frame_ms: int = 30

    # Lớp 2 — Segment quality gate (áp dụng cho cả local + API, CHẠY TRƯỚC transcribe)
    min_segment_duration_ms: int = 500    # Bỏ segment quá ngắn (speech thật thường >500ms)
    min_segment_rms: float = 0.02         # RMS tổng thể của segment (lọc noise liên tục mức thấp)
    min_active_ratio: float = 0.35        # % frame có energy > speech_threshold (lọc typing/click rời rạc)

    # Lớp 3 — Silero VAD (deep-learning VAD, tuỳ chọn)
    use_silero_vad: bool = False          # Yêu cầu: pip install silero-vad
    silero_speech_prob: float = 0.5       # Xác suất speech tối thiểu (0.0-1.0)


@dataclass
class STTConfig:
    engine: str = "faster-whisper"
    model: str = "medium"
    device: str = "cuda"
    compute_type: str = "float16"
    language: Optional[str] = None
    beam_size: int = 5
    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""
    api_model: str = "whisper-1"
    # ── Chống hallucination ──────────────────────────────────────────
    # Bật Silero VAD trong faster-whisper để cắt im lặng trước khi decode.
    vad_filter: bool = True
    # Xác suất "no speech" tối thiểu để reject segment (Whisper native).
    no_speech_threshold: float = 0.6
    # Log-probability trung bình thấp hơn ngưỡng này → reject.
    log_prob_threshold: float = -1.0
    # Compression ratio cao bất thường = lặp/ảo giác → reject.
    compression_ratio_threshold: float = 2.4
    # Gợi ý ngữ cảnh mồi cho Whisper (có thể để trống).
    initial_prompt: str = ""
    # Danh sách câu Whisper hay ảo giác — match case-insensitive substring.
    hallucination_blocklist: list[str] = field(default_factory=lambda: [
        "thank you for watching",
        "thanks for watching",
        "please subscribe",
        "like and subscribe",
        "see you next time",
        "see you in the next video",
        "cảm ơn các bạn đã xem",
        "cảm ơn các bạn đã theo dõi",
        "đừng quên like và subscribe",
        "hẹn gặp lại các bạn",
        "ご視聴ありがとうございました",
        "字幕志愿者",
        "by h.",
    ])


@dataclass
class DiarizationConfig:
    enabled: bool = False
    provider: str = "pyannote"
    model: str = "pyannote/speaker-diarization-community-1"
    huggingface_token: str = ""
    device: str = "cuda"
    window_ms: int = 12000
    max_speakers: int = 8
    num_speakers: int = 0


@dataclass
class LLMConfig:
    enabled: bool = False
    provider: str = "ollama"
    base_url: str = "http://localhost:11434/v1"
    api_key: str = "ollama"
    model: str = "qwen2.5:7b"
    target_language: str = "Vietnamese"
    context_segments: int = 5
    temperature: float = 0.3
    custom_prompt: str = ""
    glossary: str = ""                  # Terminology pairs, one per line (e.g. "ML -> Machine Learning")
    reference_text: str = ""            # Original manuscript / transcript for context
    correction_instructions: str = ""   # Correction requirements for rewrite
    batch_size: int = 1
    thread_count: int = 5
    transcript_save_dir: str = ""


@dataclass
class UIConfig:
    opacity: float = 0.95
    transcript_bg_opacity: float = 1.0
    font_size: int = 16
    font_color: str = "#FFFFFF"
    shadow_color: str = "#000000"
    show_original: bool = True
    max_lines: int = 6
    position: str = "bottom-right"
    always_on_top: bool = True
    width: int = 700
    height: int = 260


@dataclass
class OutputConfig:
    srt_dir: str = "~/Desktop"
    auto_name: bool = True


@dataclass
class AppConfig:
    audio: AudioConfig = field(default_factory=AudioConfig)
    vad: VADConfig = field(default_factory=VADConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    diarization: DiarizationConfig = field(default_factory=DiarizationConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    output: OutputConfig = field(default_factory=OutputConfig)


# ── Loader ────────────────────────────────────────────────────────────────────

def _merge(dataclass_instance, data: dict):
    """Ghi đè các field của dataclass bằng giá trị từ dict (bỏ qua key không tồn tại)."""
    for key, value in data.items():
        if hasattr(dataclass_instance, key):
            setattr(dataclass_instance, key, value)


def load_config(path: Optional[str] = None) -> AppConfig:
    """Load AppConfig từ file YAML. Dùng settings.yaml mặc định nếu không chỉ định."""
    if path is None:
        # Tìm settings.yaml tương đối với thư mục project
        base = Path(__file__).parent.parent
        path = str(base / "config" / "settings.yaml")

    cfg = AppConfig()

    if not os.path.exists(path):
        print(f"[config] Không tìm thấy {path}, dùng cấu hình mặc định.")
        return cfg

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if "audio" in raw:
        _merge(cfg.audio, raw["audio"])
    if "vad" in raw:
        _merge(cfg.vad, raw["vad"])
    if "stt" in raw:
        _merge(cfg.stt, raw["stt"])
    if "diarization" in raw:
        _merge(cfg.diarization, raw["diarization"])
    if "llm" in raw:
        _merge(cfg.llm, raw["llm"])
    if "ui" in raw:
        _merge(cfg.ui, raw["ui"])
    if "output" in raw:
        _merge(cfg.output, raw["output"])

    # Override từ biến môi trường
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if openai_api_key:
        cfg.stt.api_key = openai_api_key
        if (
            not cfg.llm.api_key
            and (
                cfg.llm.provider == "openai"
                or "api.openai.com" in cfg.llm.base_url
            )
        ):
            cfg.llm.api_key = openai_api_key

    huggingface_token = (
        os.environ.get("HUGGINGFACE_TOKEN")
        or os.environ.get("HF_TOKEN")
    )
    if huggingface_token and not cfg.diarization.huggingface_token:
        cfg.diarization.huggingface_token = huggingface_token

    return cfg


def save_config_section(section: str, data: dict, path: Optional[str] = None) -> None:
    """Cập nhật một section trong settings.yaml, giữ nguyên comments ở các section khác.

    Thay thế toàn bộ nội dung của section (từ "section:" đến section tiếp theo)
    bằng dữ liệu mới, giữ nguyên phần còn lại của file.
    """
    if path is None:
        base = Path(__file__).parent.parent
        path = str(base / "config" / "settings.yaml")

    if not os.path.exists(path):
        # No file yet, write fresh
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump({section: data}, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False)
        return

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Find the section boundaries
    section_start = None
    section_end = None
    for i, line in enumerate(lines):
        if line.rstrip() == f"{section}:" or line.startswith(f"{section}:"):
            section_start = i
        elif section_start is not None and section_end is None:
            # Next top-level key (non-indented, non-comment, non-blank)
            stripped = line.rstrip()
            if stripped and not stripped.startswith(" ") and not stripped.startswith("#"):
                section_end = i
                break

    if section_start is None:
        # Section not found, append at end
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n")
            yaml.dump({section: data}, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False)
        return

    if section_end is None:
        section_end = len(lines)

    # Generate new section content
    new_section = yaml.dump({section: data}, default_flow_style=False,
                            allow_unicode=True, sort_keys=False)

    # Rebuild file: before + new section + after
    result = lines[:section_start] + [new_section + "\n"] + lines[section_end:]

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(result)
