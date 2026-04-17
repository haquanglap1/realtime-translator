# RealtimeTranslator — CLAUDE.md

## Su menh du an
Xay dung va duy tri ung dung dich thuat real-time, don gian, dang tin cay, de kiem thu, de mo rong.
Uu tien tinh dung, kha nang bao tri, va trai nghiem nguoi dung hon su phuc tap khong can thiet.

## Mo ta du an
Ung dung desktop dich thuat real-time, ket hop:
- **Audio capture** tu moi nguon (micro, system audio / loopback via WASAPI)
- **VAD** bang energy-based algorithm (RMS threshold)
- **STT** bang Whisper (local faster-whisper hoac OpenAI-compatible API)
- **Speaker diarization** bang pyannote.audio (tuy chon)
- **Dich thuat** bang LLM (OpenAI-compatible API: Ollama, OpenAI, Groq, DeepSeek, SiliconCloud, LM Studio)
- **Rewrite** — dich lai toan bo transcript voi glossary, reference text, correction instructions
- **UI overlay** hien thi transcript + ban dich song ngu (PyQt6, frameless, always-on-top)
- **Auto-save transcript** khi Stop, luu file .txt theo timestamp

## Muc tieu san pham
- Dua ra gia tri cho nguoi dung theo tung buoc nho, hoat dong duoc ngay.
- Giu app on dinh khi them tinh nang moi.
- Uu tien giai phap da duoc chung minh, don gian, thay vi truu tuong hoa phuc tap.
- Giam thieu regression.

---

## Tech Stack

| Layer | Cong nghe | Ly do chon |
|-------|-----------|------------|
| Language | Python 3.11+ | He sinh thai ML tot nhat |
| Audio capture | `sounddevice` + `pyaudiowpatch` (WASAPI loopback) | Bat system audio & mic tren Windows |
| VAD | Energy-based (RMS threshold) | Don gian, khong can model, do tre thap |
| STT | `faster-whisper` (local) / OpenAI Whisper API | GPU acceleration, offline support |
| Speaker diarization | `pyannote.audio` (tuy chon) | Phan biet nguoi noi tren cung 1 luong audio |
| LLM translation | `openai` SDK (OpenAI-compatible) | Dung duoc Ollama, Groq, OpenAI, DeepSeek, SiliconCloud, LM Studio |
| UI | `PyQt6` | Native widget, overlay window, frameless |
| Config | `dataclasses` + YAML (`pyyaml`) | Don gian, khong can pydantic |
| Model management | `huggingface_hub` | Tai va quan ly Whisper models |
| Packaging | `PyInstaller` + `uv` | Build executable, dependency management |

---

## Cau truc thu muc (thuc te)

```
realtime-translator/
├── CLAUDE.md                  # File nay
├── INSTALL.md                 # Huong dan cai dat cho end-user va developer
├── pyproject.toml             # Dependencies & build config (uv + hatchling)
├── main.py                    # Entry point — parse args, khoi tao Pipeline + MainWindow
├── main.spec                  # PyInstaller spec (directory distribution)
├── build.bat                  # Script build executable
├── package.bat                # Script dong goi RealtimeTranslator-Setup cho end-user
├── uv.lock                   # Lock file
│
├── config/
│   ├── settings.yaml          # Cau hinh hien tai (KHONG commit — chua API keys)
│   ├── settings.yaml.example  # Cau hinh mau (commit, khong chua secret)
│   └── prompts.yaml           # System prompt cho LLM translation (tham khao, khong dung truc tiep)
│
├── core/                      # Business logic, KHONG phu thuoc UI
│   ├── __init__.py
│   ├── audio_capture.py       # AudioCapture: bat mic + system audio (WASAPI loopback via pyaudiowpatch, fallback sounddevice)
│   │                          #   - AudioChunk dataclass (audio, source_label, speaker_label)
│   │                          #   - list_devices(), find_loopback_device(), find_default_mic_device()
│   │                          #   - Resample tu native SR -> 16kHz
│   ├── vad.py                 # EnergyVAD: phat hien speech bang RMS energy
│   │                          #   - SpeechSegment dataclass (audio, start_ms, end_ms, duration_ms, source/speaker_label)
│   │                          #   - process() -> list[SpeechSegment], flush(), reset()
│   ├── transcriber.py         # BaseTranscriber -> FasterWhisperTranscriber, OpenAIWhisperTranscriber
│   │                          #   - TranscriptSegment dataclass (id, text, language, start/end_ms, speaker_label, translated)
│   │                          #   - create_transcriber(config) factory
│   │                          #   - Duplicate text detection (skip repeated segments)
│   ├── translator.py          # Translator: LLM translation + rewrite
│   │                          #   - translate(text, context) -> str — dich tung batch
│   │                          #   - rewrite_transcript(segments, context) -> list[str] — dich lai toan bo
│   │                          #   - System prompts: SYSTEM_PROMPT_TEMPLATE, REWRITE_SYSTEM_PROMPT_TEMPLATE
│   │                          #   - Ho tro: custom_prompt, glossary, reference_text, correction_instructions
│   ├── diarizer.py            # BaseDiarizer -> PyannoteDiarizer
│   │                          #   - DiarizedTurn dataclass (start_ms, end_ms, speaker_id)
│   │                          #   - create_diarizer(config) factory
│   │                          #   - Can HuggingFace token + model pyannote/speaker-diarization-community-1
│   └── pipeline.py            # Pipeline: orchestrate toan bo, multi-threaded
│                              #   Thread 1: sounddevice callback -> AudioCapture.buffer (RingBuffer)
│                              #   Thread 2: _vad_loop — buffer -> VAD -> speech_queue
│                              #   Thread 3: _transcriber_loop — speech_queue -> Whisper -> on_result
│                              #   Thread 4: _diarizer_loop (tuy chon) — pyannote -> speaker updates
│                              #   Thread 5: _translator_loop — translation_queue -> LLM -> on_translation
│                              #   Thread 6: main/Qt — signals update UI
│                              #   + _rewrite_worker (on-demand) — rewrite toan bo transcript
│                              #   - Batch translation voi batch_size + thread pool
│                              #   - Speaker reconciliation across diarization windows
│                              #   - Auto-save rewritten translation to .txt
│
├── ui/                        # Giao dien nguoi dung (PyQt6)
│   ├── __init__.py
│   ├── main_window.py         # MainWindow (QWidget): overlay chinh
│   │                          #   - Frameless, always-on-top, semi-transparent, draggable, resizable
│   │                          #   - Header: Mode toggle, Models, STT, LLM, A-/A+, T-/T+, Clear, Exit
│   │                          #   - Body: scrollable transcript (speaker tag + original + translated)
│   │                          #   - Footer: status label, Start/Stop, Rewrite buttons
│   │                          #   - 3 display modes: Song ngu, Chi Dich, Chi Goc
│   │                          #   - Signals: transcript_received, translation_received, status_changed, rewrite_state_changed
│   │                          #   - Auto-save transcript khi Stop (neu co transcript_save_dir)
│   ├── stt_config.py          # STTConfigDialog: cau hinh audio source, STT engine, speaker labeling
│   │                          #   - Audio source: mic / loopback / both
│   │                          #   - Speaker strategy: source / language / pyannote
│   │                          #   - STT engine: faster-whisper (local) / openai-api
│   │                          #   - STT API presets: OpenAI, Groq, Custom
│   │                          #   - Pyannote diarization settings (HF token, num/max speakers)
│   │                          #   - Luu vao settings.yaml (save_config_section)
│   ├── llm_config.py          # LLMConfigDialog: cau hinh LLM translation
│   │                          #   - Provider presets: Ollama, LM Studio, OpenAI, DeepSeek, Groq, SiliconCloud, Custom
│   │                          #   - Remote model listing via /models API
│   │                          #   - Custom prompt, target language
│   │                          #   - Rewrite fields: glossary, reference text, correction instructions
│   │                          #   - Batch size, thread count, transcript save dir
│   │                          #   - Enable/disable toggle
│   │                          #   - Connection test (background thread)
│   │                          #   - Luu vao settings.yaml (save_config_section)
│   └── model_manager.py       # ModelManagerDialog: tai va quan ly Whisper models
│                              #   - Hien thi bang model: ten, kich thuoc, trang thai, download/delete
│                              #   - Models: tiny (77MB), base (145MB), small (484MB), medium (1.5GB), large-v3 (3GB), large-v3-turbo (1.7GB)
│                              #   - Background download voi progress bar
│                              #   - Thread-safe via pyqtSignal
│
├── utils/                     # Utilities dung chung
│   ├── __init__.py
│   ├── config.py              # AppConfig + sub-configs (dataclasses), load_config(), save_config_section()
│   │                          #   - AudioConfig, VADConfig, STTConfig, DiarizationConfig, LLMConfig, UIConfig, OutputConfig
│   │                          #   - Load tu YAML, merge voi env vars (OPENAI_API_KEY, HF_TOKEN)
│   │                          #   - save_config_section() — cap nhat 1 section trong settings.yaml, giu nguyen phan con lai
│   ├── ring_buffer.py         # RingBuffer: thread-safe circular buffer (deque + Event)
│   │                          #   - put(), get(timeout), get_all(), clear()
│   ├── model_manager.py       # Backend logic cho Whisper model management
│   │                          #   - WHISPER_MODELS registry, is_model_downloaded(), delete_model()
│   │                          #   - ModelDownloader: background download via huggingface_hub.snapshot_download
│   ├── stereo_mix.py          # Helper kiem tra va huong dan bat Stereo Mix tren Windows
│   └── torch_setup.py         # Auto-detect va cai dat PyTorch + CUDA (cu128 cho RTX 5070)
│                              #   - check_torch_cuda(), install_torch_cuda(), ensure_torch()
│
├── installer/                 # Scripts cho end-user installer
│   ├── install.bat            # Tu dong tai Python + cai dependencies
│   └── run.bat                # Launcher
│
├── RealtimeTranslator-Setup/  # Output cua package.bat (dong goi cho end-user)
├── build/                     # Output cua PyInstaller
└── dist/                      # Output cua PyInstaller
```

---

## Pipeline chinh

```
[Audio Source: mic / loopback / both]
     │
     ▼  (sounddevice / pyaudiowpatch callback)
[RingBuffer] ◄─── AudioChunk(audio, source_label, speaker_label)
     │
     ▼  (Thread 2: _vad_loop)
[EnergyVAD] ─── RMS energy > threshold → SpeechSegment (2-3 giay)
     │
     ▼  (Thread 3: _transcriber_loop)
[Transcriber] ─── faster-whisper / Whisper API → TranscriptSegment
     │
     ├──► [UI: on_result] ─── hien thi transcript ngay lap tuc
     │
     ├──► [Thread 4: _diarizer_loop] (tuy chon, pyannote)
     │         └──► gan speaker_label → [UI: on_translation]
     │
     ▼  (Thread 5: _translator_loop)
[Translator] ─── LLM batch translation voi context → translated text
     │
     ▼
[UI: on_translation] ─── cap nhat ban dich
     │
[Auto-save] ─── khi Stop → luu transcript .txt
     │
[Rewrite] ─── on-demand → dich lai toan bo voi glossary/reference → luu .txt
```

---

## Data Models

```python
@dataclass
class AudioChunk:
    audio: np.ndarray       # float32, 16kHz mono
    source_label: str       # "mic" | "loopback" | "mixed"
    speaker_label: str      # "Speaker 1" | "Speaker 2"

@dataclass
class SpeechSegment:
    audio: np.ndarray
    start_ms: int
    end_ms: int
    duration_ms: int
    source_label: str
    speaker_label: str

@dataclass
class TranscriptSegment:
    id: int
    text: str               # raw transcript
    language: str            # detected language code ("en", "vi", ...)
    start_ms: int
    end_ms: int
    duration_ms: int
    engine_latency_ms: int
    speaker_label: str       # "Speaker 1" | "Speaker 2"
    source_label: str        # "mic" | "loopback"
    translated: Optional[str]  # ban dich (None neu chua dich)

@dataclass
class DiarizedTurn:
    start_ms: int
    end_ms: int
    speaker_id: str          # raw speaker ID tu pyannote

@dataclass
class TimedAudioChunk:       # Luu tru audio history cho diarization
    audio: np.ndarray
    start_ms: int
    end_ms: int

@dataclass
class SpeakerTurnRecord:     # Luu tru speaker turn history
    start_ms: int
    end_ms: int
    speaker_label: str       # "Speaker 1" | "Speaker 2" (resolved)
```

---

## Config Schema (settings.yaml)

```yaml
audio:
  source: loopback           # "mic" | "loopback" | "both"
  speaker_strategy: source   # "source" | "language" | "pyannote"
  device_index: null          # null = auto-detect
  sample_rate: 16000
  channels: 1
  blocksize: 1600            # callback block size (100ms tai 16kHz)

diarization:
  enabled: false
  provider: pyannote
  model: pyannote/speaker-diarization-community-1
  huggingface_token: ""       # HuggingFace token (required cho pyannote)
  device: cuda
  window_ms: 12000            # audio window cho diarization
  max_speakers: 2
  num_speakers: 0             # 0 = auto-detect

vad:
  speech_threshold: 0.012     # RMS energy threshold (0.0-1.0)
  min_speech_frames: 10       # min frames de tinh la speech (~300ms)
  silence_frames_to_end: 10   # frames im lang truoc khi cat segment (~300ms)
  max_speech_frames: 100      # max 1 segment (~3 giay)
  frame_ms: 30                # frame size: 30ms tai 16kHz

stt:
  engine: faster-whisper      # "faster-whisper" | "openai-api"
  model: medium               # tiny/base/small/medium/large-v3/large-v3-turbo
  device: cuda                # "cuda" | "cpu"
  compute_type: float16       # "float16" | "int8" | "float32"
  language: null              # null = auto-detect
  beam_size: 5
  api_base: "https://api.openai.com/v1"
  api_key: ""
  api_model: whisper-1

llm:
  enabled: false
  provider: ollama            # "ollama" | "openai" | "groq" | "deepseek" | "siliconcloud" | "lm-studio" | "custom"
  base_url: "http://localhost:11434/v1"
  api_key: "ollama"
  model: "qwen2.5:7b"
  target_language: Vietnamese
  context_segments: 5
  temperature: 0.3
  custom_prompt: ""           # Lenh dieu huong them cho LLM
  glossary: ""                # Bang thuat ngu (cho Rewrite)
  reference_text: ""          # Van ban goc/ban thao (cho Rewrite)
  correction_instructions: "" # Yeu cau chinh sua (cho Rewrite)
  batch_size: 1               # So segment gom lai truoc khi gui LLM
  thread_count: 5             # So thread dich song song
  transcript_save_dir: ""     # Thu muc luu transcript khi Stop

ui:
  opacity: 0.88
  font_size: 16
  font_color: "#FFFFFF"
  shadow_color: "#000000"
  show_original: true
  max_lines: 6
  position: "bottom-right"    # "bottom-right" | "bottom-left" | "top-right" | "top-left"
  always_on_top: true
  width: 700
  height: 260

output:
  srt_dir: "~/Desktop"
  auto_name: true
```

---

## LLM Translation Prompt

### Realtime translation (SYSTEM_PROMPT_TEMPLATE)
```
You are a professional real-time translator specializing in {target_language}.

<guidelines>
- Translate the given text into {target_language} naturally and fluently
- Follow {target_language} expression conventions
- Keep speaker point of view and subject references consistent
- Speaker tags like [Speaker 1] are for context only, do not copy to output
- For proper nouns or technical terms, keep the original or transliterate
- If a sentence is incomplete, translate what you have naturally
- Maintain consistency with previous context provided
- The input may contain transcription errors; use context to infer the intended meaning
</guidelines>

<output_rules>
- Return ONLY the translated text
- Do NOT add explanations, notes, or quotation marks
- Each sentence on its own line
</output_rules>
```

### Rewrite (REWRITE_SYSTEM_PROMPT_TEMPLATE)
```
You are a professional translator and editor specializing in {target_language}.

<task>
- Translate the full transcript into {target_language}
- Rewrite so it reads naturally, smoothly, and coherently
- Fix likely transcription mistakes
- Return EXACTLY one output line per input segment: <id>TAB<translation>
</task>

+ Optional blocks: <glossary>, <reference_manuscript>, <correction_instructions>, <custom_instructions>
```

---

## Speaker Labeling Strategies

| Strategy | Cach gan speaker | Khi nao dung |
|----------|-----------------|--------------|
| `source` | Mic = Speaker 1, Loopback = Speaker 2 | Khi dung `both` (2 nguon audio) |
| `language` | Target lang = Speaker 2, khac = Speaker 1 | 1 nguon audio, 2 ngon ngu |
| `pyannote` | Pyannote diarization (AI model) | 1 nguon audio, nhieu nguoi noi cung ngon ngu |

---

## Thread Model

```
Thread 1 (sounddevice/pyaudiowpatch internal):
    audio callback -> AudioCapture.buffer (RingBuffer, maxsize=300)

Thread 2 (_vad_loop):
    buffer.get() -> EnergyVAD.process() -> speech_queue (maxsize=20)
    - Moi source_label co VAD rieng
    - Ghi audio history cho diarization

Thread 3 (_transcriber_loop):
    speech_queue.get() -> Transcriber.transcribe() -> on_result callback
    - Gan speaker_label theo strategy
    - Gui vao diarization_queue hoac translation_queue

Thread 4 (_diarizer_loop) [tuy chon, khi pyannote enabled]:
    diarization_queue.get() -> PyannoteDiarizer.diarize_window()
    - Slice audio window tu history
    - Reconcile speaker labels across windows
    - Update segment.speaker_label -> on_translation callback
    - Forward to translation_queue

Thread 5 (_translator_loop):
    translation_queue.get() -> Translator.translate() via ThreadPoolExecutor
    - Batch segments theo batch_size + idle timeout (0.5s)
    - Context window: N segment truoc
    - Skip translation neu detected language = target language
    - on_translation callback

Thread 6 (main/Qt):
    pyqtSignal -> update UI (transcript_received, translation_received, status_changed)

Rewrite Thread (on-demand, khi user bam Rewrite):
    _rewrite_worker() -> Translator.rewrite_transcript() -> on_translation
    - Tao Translator moi (khong share voi realtime translator)
    - Luu ket qua vao file .txt
```

---

## Cac lenh phat trien

```bash
# Cai dependencies
uv sync

# Chay app
uv run python main.py

# Chay voi tuy chon
uv run python main.py --source mic
uv run python main.py --model large-v3
uv run python main.py --device cpu
uv run python main.py --list-devices
uv run python main.py --config path/to/settings.yaml

# Chay test
uv run pytest tests/

# Build executable
build.bat
# hoac:
uv run pyinstaller main.spec --noconfirm

# Dong goi cho end-user
package.bat
```

---

## Dependencies (pyproject.toml)

```
sounddevice>=0.4.6          # Audio capture
numpy>=1.24                 # Audio processing
faster-whisper>=1.1.0       # Local Whisper STT
PyQt6>=6.6.0                # UI framework
pyyaml>=6.0                 # Config loading
openai>=1.30.0              # LLM API client
huggingface-hub>=0.20.0     # Model download
pyaudiowpatch>=0.2.12       # WASAPI loopback (Windows)
pyannote.audio>=4.0.4       # Speaker diarization

# Dev:
pytest>=8.0
pyinstaller>=6.0
```

---

## Phong cach lam viec
- Truoc khi thuc hien bat ky thay doi khong tam thuong nao, giai thich:
  1. Van de la gi,
  2. Nguyen nhan goc,
  3. Phuong an sua,
  4. Cac file bi anh huong.
- Voi tinh nang lon hoac tai cau truc, tao ke hoach trien khai ngan truoc.
- Khong viet lai toan bo khi chi can sua cuc bo.
- Giu nguyen hanh vi hien co tru khi yeu cau ro rang thay doi no.

## Quy tac kien truc
- Tuan theo cau truc thu muc va quy uoc dat ten hien co.
- Giu business logic tach biet khoi UI components.
- Phan chia ro rang:
  - UI / trinh bay (`ui/`)
  - Logic ung dung (`core/`)
  - Utilities (`utils/`)
  - Cau hinh (`config/`)
- Uu tien module nho, tap trung thay vi file lon da muc dich.
- Tai su dung tien ich hien co truoc khi tao moi.
- Chi xoa dead code khi chac chan no khong con duoc dung.

## Quy tac chat luong code
- Viet code de doc truoc.
- Uu tien ten bien/ham ro rang thay vi ten ngan.
- Moi ham chi lam mot viec.
- Tranh side-effect an.
- Tranh logic trung lap; tach utility dung chung khi thay trung lap tu 2 lan tro len.
- Chi them comment khi y dinh khong ro rang tu code.
- Khong tao abstraction khong can thiet cho nhu cau gia dinh tuong lai.

## Quy tac an toan
- Khong hardcode secret, API key, token, password, hoac URL private.
- Dung bien moi truong cho secret.
- Khong lam yeu xac thuc, phan quyen, hoac validate de "chay cho nhanh".
- Validate tat ca input tu ben ngoai.
- Escape hoac sanitize du lieu render vao HTML/UI khi can.
- Coi cac thao tac file, thanh toan, auth, hanh dong xoa du lieu la vung rui ro cao.

## Quy tac dependency
- Uu tien dependency hien co trong project.
- Khong them package moi tru khi no giam dang ke do phuc tap.
- Khi them package, giai thich ly do va cac phuong an thay the da xem xet.
- Tranh dependency co chuc nang trung lap.

## Quy tac UI/UX
- Giu UI don gian, ro rang, nhat quan.
- Dam bao du cac trang thai: loading, empty, error, success cho moi man hinh quan trong.
- Form phai ben vung, than thien nguoi dung.
- Uu tien markup de truy cap va tuong tac ban phim.
- Khong ship layout vo hoac khong nhat quan truc quan.

## Quy tac du lieu va API
- Giu API contract ro rang.
- Xu ly an toan: null, empty, timeout, error response.
- Khong gia dinh du lieu backend luon hop le.
- Log thong tin debug huu ich, khong de lo secret.
- Voi thay doi schema, giai thich anh huong migration va rui ro rollback.

## Kiem thu va xac minh
- Sau moi thay doi co y nghia, xac minh ket qua.
- Checklist xac minh toi thieu:
  - Code compile duoc,
  - Lint/type check pass (neu co),
  - Flow bi anh huong hoat dong end-to-end,
  - Khong regression ro rang o tinh nang lan can.
- Voi fix bug: ghi ro buoc tai hien va cach fix ngan lap lai.
- Voi UI: xac minh truc quan, mo ta thay doi.
- Voi backend logic: xac minh bang test hoac test case thu cong.

## Quy tac debug
- Tai hien loi truoc khi sua (khi co the).
- Khong doan mo.
- Kiem tra log, thong bao loi, network request, state transition.
- Sua nguyen nhan goc, khong chi trieu chung.
- Neu nguyen nhan goc chua ro, noi thang va thu hep kha nang.

## Quy tac chinh sua file
- Chi thay doi file can thiet cho task.
- Giu diff nho, de review.
- Khong doi ten hoac di chuyen file tru khi co ly do manh.
- Khong xoa file ma khong giai thich ly do.

## Quy tac tai cau truc
- Chi refactor khi cai thien ro rang su ro rang, do tin cay, hoac tai su dung.
- Tranh tron refactor voi tinh nang moi tru khi can thiet.
- Giu nguyen hanh vi public trong qua trinh refactor.
- Canh bao ro moi refactor co rui ro truoc khi ap dung.

## Nguyen tac phat trien cu the cho du an
1. **Multi-threaded pipeline**: Dung threading + queue.Queue giua audio thread va processing threads
2. **Non-blocking UI**: UI thread khong bao gio block — tat ca processing chay background threads
3. **Graceful degradation**: Neu LLM cham → hien thi transcript truoc, ban dich cap nhat sau
4. **Context-aware translation**: Luon gui N segment truoc de LLM hieu ngu canh
5. **Batch translation**: Gom nhieu segment thanh 1 request de giam latency + overhead
6. **Skip target language**: Khong dich neu detected language = target language
7. **Speaker reconciliation**: Diarization speaker IDs duoc reconcile across windows de consistent
8. **Local-first**: Uu tien Whisper local + Ollama local, API la fallback
9. **Config persistence**: Thay doi settings tu UI duoc luu vao settings.yaml ngay lap tuc

---

## Luu y Windows-specific
- System audio loopback: uu tien pyaudiowpatch (WASAPI loopback), fallback sounddevice + Stereo Mix
- Can cai CUDA toolkit 12.x neu dung GPU voi faster-whisper (RTX 5070: cu128)
- PyQt6 tren Windows can `pip install PyQt6` (khong can build tu source)
- Ollama chay local: `ollama serve` truoc khi start app
- torch_setup.py tu dong cai PyTorch + CUDA neu chua co

---

## Format ban giao
Khi hoan thanh task:
1. Tom tat thay doi,
2. Liet ke file da chinh sua,
3. Ghi nhan cac gia dinh,
4. Ket qua xac minh,
5. Rui ro con lai hoac buoc tiep theo.

## Khi yeu cau khong ro rang
- Khong tu bia yeu cau san pham.
- Suy luan tu code va pattern hien co khi hop ly.
- Neu ro gia dinh.
- Uu tien trien khai nho nhat, an toan nhat.

## Anti-pattern can tranh
- Component qua lon
- Logic business bi trung lap
- Hang so magic rai rac trong code
- Xu ly loi im lang (silent failure)
- Viet lai toan bo khong co ly do
- Luong chinh chua hoan thien, chi co TODO
- Them package cho utility nho le

## Dinh nghia "hoan thanh"
Task chua hoan thanh cho den khi:
- Hanh vi duoc yeu cau da trien khai,
- Luong bi anh huong da xac minh,
- Khong con loi ro rang,
- Thay doi duoc giai thich ro rang,
- Rui ro va cong viec tiep theo da ghi nhan.

---

## Roadmap

- [x] **v0.1** — Pipeline co ban: audio capture → Whisper → display transcript
- [x] **v0.2** — LLM translation + hien thi song ngu + batch translation + multi-thread
- [ ] **v0.3** — SRT export
- [x] **v0.4** — Settings dialog (chon device, model, ngon ngu, LLM provider)
- [x] **v0.4.1** — Speaker diarization (pyannote.audio) + speaker labeling strategies
- [x] **v0.4.2** — Rewrite feature (dich lai toan bo transcript voi glossary/reference/correction)
- [x] **v0.4.3** — Model Manager (tai/xoa Whisper models tu UI)
- [ ] **v0.5** — System tray, overlay UI dep, SRT export
- [ ] **v0.6** — Ho tro ca mic + loopback dong thoi (da co co ban)
- [ ] **v0.7** — Whisper API fallback, nhieu LLM provider (da co co ban)
- [ ] **v1.0** — Package executable, installer (da co build.bat + package.bat)
