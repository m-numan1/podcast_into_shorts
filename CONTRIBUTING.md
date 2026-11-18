# Contributing to podcast_into_shorts

Thank you for your interest in improving this project! We welcome community contributions, bug fixes, and suggestions.

---

## Getting Started

### 1. Prerequisites
- **Python**: Version 3.10 or higher.
- **FFmpeg & FFprobe**: Required on your system PATH for extracting audio, analyzing durations, and rendering clips.
  - Windows: `winget install Gyan.FFmpeg`
  - macOS: `brew install ffmpeg`
  - Linux: `sudo apt install ffmpeg`

### 2. Development Setup

Clone the repository and set up a virtual environment:

```bash
git clone https://github.com/m-numan1/podcast_into_shorts.git
cd podcast_into_shorts

python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install core and development dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Optional: Install faster-whisper for offline speech transcription
pip install -r requirements-ml.txt
```

Copy the environment template:
```bash
cp .env.example .env
```

---

## Code Quality & Verification

Every pull request must pass both static lint checks and automated unit tests.

### Running Linters
We use `ruff` for linting and code formatting checks:
```bash
ruff check .
```

### Running Tests
Execute the full test suite using `pytest`:
```bash
pytest
```
To run specific test modules:
```bash
pytest tests/test_nlp.py
pytest tests/test_renderer.py
```

---

## Architectural Guidelines & Invariants

When adding features or modifying existing logic, please adhere to these core principles:

1. **No Silent Failures**: Never swallow exceptions silently with bare `except: pass`. Errors should either be properly recovered, logged with context, or propagated using the custom exception types defined in `src/errors.py`.
2. **Library Code Logging**: Library modules inside `src/` must use the configured logger (`src.utils.logging_config.get_logger`), not `print()` statements. CLI entry points (`main.py`) and server scripts (`app.py`) may print user-facing output.
3. **Transparent Provenance**: Output metadata must honestly reflect whether clips were scored via an LLM or via heuristic metrics, and whether transcripts came from fixtures or real media.
4. **Defensive Processing**: Guard against unbounded loops or runaway chunks. All segmentation routines enforce minimum and maximum duration boundaries.

---

## Submitting a Pull Request

1. Fork the repository and create a new feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Implement your changes and add corresponding unit tests in `tests/`.
3. Verify that `ruff check .` and `pytest` pass cleanly.
4. Commit your changes with descriptive messages:
   ```bash
   git commit -m "feat: add feature description"
   ```
5. Push to your fork and submit a Pull Request against the `main` branch.
