# RealtimeTranslator - Huong dan cai dat

## Cach 1: Bo cai dat tu dong (KHUYEN NGHI)

Day la cach don gian nhat de cai tren may khac. Bo cai se tu dong tai Python, cai tat ca dependencies (bao gom pyannote.audio, torch, faster-whisper, ...).

### Yeu cau may dich
- Windows 10/11 (64-bit)
- Ket noi internet (de tai Python + dependencies)
- GPU NVIDIA + CUDA Toolkit 12.x (tuy chon, neu dung GPU)
- Dung luong: ~3-5 GB sau cai dat

### Buoc 1: Dong goi tren may dev

Tren may phat trien (may ban), chay:

```
package.bat
```

Se tao thu muc `RealtimeTranslator-Setup/` chua:
```
RealtimeTranslator-Setup/
  install.bat          <- Script cai dat tu dong
  run.bat              <- Launcher
  app/                 <- Source code (KHONG co API keys)
    main.py
    core/
    ui/
    utils/
    config/
      settings.yaml.example
      prompts.yaml
```

Nen zip thu muc nay va gui cho nguoi dung.

### Buoc 2: Cai dat tren may dich

Nguoi nhan:

1. **Giai nen** file zip
2. **Chay `install.bat`** (click phai > Run as Administrator neu can)
   - Tu dong tai Python 3.12 embedded
   - Tu dong cai pip + virtualenv
   - Tu dong cai tat ca dependencies (torch, pyannote.audio, faster-whisper, PyQt6, ...)
   - Mat khoang 5-15 phut tuy toc do mang
3. **Chinh sua `app\config\settings.yaml`** (dien API keys)
4. **Chay `run.bat`** de khoi dong app

### Cau hinh toi thieu (settings.yaml)

**Neu dung Whisper local (khong can API):**
```yaml
stt:
  engine: faster-whisper
  model: medium
  device: cuda           # hoac "cpu" neu khong co GPU
```

**Neu dung Whisper API (Groq mien phi):**
```yaml
stt:
  engine: openai-api
  api_base: "https://api.groq.com/openai/v1"
  api_key: "gsk_YOUR_GROQ_API_KEY"
  api_model: whisper-large-v3
```

**Neu muon bat dich thuat LLM:**
```yaml
llm:
  enabled: true
  provider: ollama
  base_url: "http://localhost:11434/v1"
  api_key: "ollama"
  model: "qwen2.5:7b"
  target_language: Vietnamese
```

### Bat loopback audio (nghe am thanh he thong)
Neu dung `source: loopback`, app se tu dung WASAPI loopback.
Neu khong hoat dong:
1. Mo **Sound Settings** > Recording tab
2. Right-click > Show Disabled Devices
3. Enable **Stereo Mix**
4. Khoi dong lai app

---

## Cach 2: Chay tu source code (cho developer)

### Yeu cau
- Python 3.11+ (khuyen nghi 3.11 hoac 3.12)
- [uv](https://docs.astral.sh/uv/) package manager
- GPU NVIDIA + CUDA Toolkit 12.x (tuy chon)

### Cai dat

```bash
cd realtime-translator

# Cai dependencies
uv sync

# Copy cau hinh
cp config/settings.yaml.example config/settings.yaml
# Chinh sua settings.yaml

# Chay app
uv run python main.py

# Chay voi tuy chon
uv run python main.py --source mic
uv run python main.py --list-devices
```

### Cai PyTorch voi CUDA (neu can GPU)
```bash
uv run pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

---

## Troubleshooting

| Van de | Giai phap |
|--------|-----------|
| install.bat loi tai Python | Kiem tra ket noi internet, thu chay lai |
| App khong mo / crash | Kiem tra CUDA Toolkit da cai chua. Thu doi `device: cpu` |
| Khong bat duoc system audio | Bat Stereo Mix hoac kiem tra WASAPI loopback |
| Model Whisper chua tai | Mo app > bam Models > tai model can dung |
| LLM khong dich | Kiem tra Ollama dang chay (`ollama serve`) hoac API key dung |
| Loi "CUDA not available" | Cai CUDA Toolkit 12.x, hoac doi `device: cpu` |
| Loi "pyannote.audio not installed" | Chay lai install.bat, dam bao cai dat thanh cong |

---

## Day du an len GitHub va phat hanh ban moi

### Buoc 1: Khoi tao git repo local

```bash
cd c:\Users\Lap-miniPC\Documents\realtime-translator
git init
git add .gitignore
git status                           # KIEM TRA: khong co settings.yaml, *.env, dist/, build/
git add .
git commit -m "Initial commit: RealtimeTranslator v0.4.3"
```

> **Quan trong**: truoc khi commit, mo `git status` kiem tra chac chan `config/settings.yaml` (chua API keys) bi ignore. Neu thay no trong danh sach, DUNG LAI — chinh lai `.gitignore` hoac chay `git rm --cached config/settings.yaml`.

### Buoc 2: Tao repo tren GitHub

1. Vao https://github.com/new
2. Repository name: `realtime-translator`
3. Visibility: **Private** (khuyen nghi, vi ban co the da de API key trong git history cu)
4. KHONG tick "Initialize with README" (vi da co code local roi)
5. Bam **Create repository**

### Buoc 3: Push len GitHub

```bash
git branch -M main
git remote add origin https://github.com/<your-username>/realtime-translator.git
git push -u origin main
```

### Buoc 4: Cau hinh auto-update

Mo file [utils/version.py](utils/version.py), sua:

```python
GITHUB_REPO = "<your-username>/realtime-translator"
```

Commit va push:

```bash
git add utils/version.py
git commit -m "Configure GitHub repo for auto-update"
git push
```

### Buoc 5: Phat hanh ban moi (release flow)

Moi khi ban muon phat hanh bat mi:

1. Bump version **dong thoi** o 2 file (phai khop nhau):
   - [pyproject.toml](pyproject.toml) → `version = "0.5.0"`
   - [utils/version.py](utils/version.py) → `__version__ = "0.5.0"`
2. Commit thay doi:
   ```bash
   git add pyproject.toml utils/version.py
   git commit -m "Bump version to 0.5.0"
   git push
   ```
3. Tao tag va push:
   ```bash
   git tag v0.5.0
   git push origin v0.5.0
   ```
4. GitHub Actions se tu dong:
   - Chay `package.bat` tao `RealtimeTranslator-Setup/`
   - Zip lai thanh `RealtimeTranslator-Setup-0.5.0.zip`
   - Tao GitHub Release voi tag `v0.5.0`, dinh kem file zip
5. Khi nguoi dung mo app, auto-updater goi `api.github.com/.../releases/latest`, neu version moi hon → hien dialog **Co ban cap nhat**, bam **Mo trang tai** → mo browser toi file zip.

Xem workflow tai [.github/workflows/release.yml](.github/workflows/release.yml).

### Cach auto-update hoat dong

- Khi MainWindow khoi tao, `check_update_async` chay trong daemon thread goi GitHub API.
- Neu tag_name cua release moi nhat > `__version__` hien tai → emit `update_available` signal.
- UI thread nhan signal, hien QMessageBox voi release notes + nut **Mo trang tai**.
- Neu khong co mang hoac API loi → silent (print log, khong lam phien user).
- Khi `GITHUB_REPO` con la `YOUR_GITHUB_USER/...` (chua cau hinh) → skip check.

### Troubleshooting release

| Van de | Giai phap |
|--------|-----------|
| Workflow fail vi `package.bat` loi | Doc log GitHub Actions, chinh sua, push tag moi (vi du `v0.5.1`) |
| Dialog update khong hien | Kiem tra `GITHUB_REPO` trong `utils/version.py` da dung, repo phai PUBLIC hoac co release public |
| Nguoi dung cu khong thay update | Chac chan ban cu dang dung `__version__` thap hon tag moi |
| Release notes trong | Them mo ta khi tao tag, hoac de `generate_release_notes: true` tu dong lay tu commit |
