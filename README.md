# podcast_into_shorts

Finds self-contained short clips in long-form podcasts, interviews and
documentaries, and optionally renders them as vertical MP4s with burned-in
captions.

Given a YouTube URL or a local media file it produces ranked clip
recommendations — timestamps, hook, summary, caption, hashtags, per-agent scores
— as JSON, and with `--render` encodes the top clips to 1080x1920 MP4.

## Requirements

**ffmpeg and ffprobe must be on PATH.** They handle audio extraction, duration
probing, silence detection and rendering.

```
Windows        winget install Gyan.FFmpeg
macOS          brew install ffmpeg
Debian/Ubuntu  sudo apt install ffmpeg
```

Python 3.10+.

## Install

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -r requirements.txt

# Optional: local Whisper transcription. Pulls ~2 GB of PyTorch.
# Without it you need a YouTube URL that has captions.
pip install -r requirements-ml.txt
```

Then copy the config template:

```bash
cp .env.example .env
```

Every setting has a working default. With no API keys the pipeline runs fully
offline in heuristic mode — see [Scoring modes](#scoring-modes).

## Usage

```bash
# Try it with no media and no keys (synthetic fixture, clearly labelled)
python main.py --demo

# A real YouTube episode
python main.py --source "https://www.youtube.com/watch?v=VIDEO_ID"

# A local file, and render the top clips to vertical MP4
python main.py --source ./episode.mp3 --render

# Web dashboard on http://127.0.0.1:8000
python app.py
```

Useful flags: `--output NAME.json`, `--max-clips N`, `--log-level DEBUG`,
`--thread-id ID` (reuse to resume an interrupted run), `--no-checkpoint`.

Exit codes: `0` success, `1` pipeline error, `2` no clips produced, `3` bad usage.

## How it works

```
                      ┌── node_08_hook ──┐
                      ├── node_08_story ─┤
 01 download          ├── node_08_edu ───┤
 02 extract audio     ├── node_08_enter ─┤
 03 transcribe   ─────┼── node_08_debate─┼──── 09 chief editor ── 10 render
 04 segment      07   ├── node_08_retain─┘        rank, dedup,      ffmpeg
 05 index      candidates                         package
 06 features
```

1. **download** — yt-dlp or local file. Duration comes from `ffprobe`, never a
   placeholder.
2. **extract audio** — 16 kHz mono WAV.
3. **transcribe** — YouTube captions if available, else local Whisper. Raw
   fragments are merged into sentence units.
4. **segment** — group units into topic chunks (see
   [Segmentation](#segmentation-why-it-works-this-way)).
5. **index** — embed chunks; powers near-duplicate detection.
6. **features** — per-chunk cue density, entities, speaking rate, measured pauses.
7. **candidates** — build clip windows, then shortlist to cap evaluation cost.
8. **six editor agents** — hook, story, educational, entertainment, debate,
   retention. Real parallel graph branches.
9. **chief editor** — composite score, deduplicate, rank, package.
10. **render** — optional. Cut, reframe to 9:16, burn captions, normalise audio.

## Scoring modes

The output always records how it was produced, in `provenance`:

| mode | when | meaning |
|---|---|---|
| `llm` | `DEFAULT_LLM_PROVIDER=openai\|gemini` with a key | Each agent scores via constrained structured output. |
| `heuristic` | default | Scored from measured signals only: cue density, speaking rate, boundary cleanliness, measured pauses. |

Heuristic mode is a **declared mode, not a silent fallback**. It is a weak proxy
for editorial judgement — useful for smoke-testing and for ordering candidates,
not for deciding what to publish. The CLI and dashboard say so on every run, and
`scoring_mode` is stamped on every clip and every agent evaluation.

`--demo` output is additionally stamped `transcript_source="fixture"` and
`is_synthetic: true`. It describes bundled sample text, not real media.

## Segmentation: why it works this way

Splitting an episode into topics is the core problem. Two approaches were tried
and measured.

**Keyword matching** (what this project used to do) fails on real input. Splitting
on a fixed phrase list works only on text containing those phrases. On real
YouTube auto-captions — 2–4 second fragments with no punctuation — nothing
matched, so a 30-minute episode became a single 1800-second chunk, which the
candidate stage then discarded, producing **zero clips** while still reporting
success.

**Embedding dip detection** is the obvious fix, and it works — but only with
genuinely semantic embeddings. Measured against planted topic boundaries, the
offline `lexical` backend does not separate topics at any comparison window size
from 2 to 10 units: the boundary/non-boundary similarity ratio stays around 1.0,
because incidental word variation between neighbouring sentences swamps the topic
signal. Shipping dip detection on that backend would be the same failure as the
keyword list — an impressive-looking component that does nothing.

So the backbone is signals that are reliable in speech:

1. **sentence structure** — punctuation, where present
2. **pause length** — the strongest real cue for a safe cut
3. **speaker turns** — where the transcript carries them
4. **hard duration bounds** — the guarantee that no chunk is unusable

Semantic dip detection is layered on top **only** when `EMBEDDING_BACKEND` is
`openai` or `gemini`, and the reason for each boundary is reported in
`boundary_reason`. Discourse markers survive as a small additive nudge, not as
the mechanism.

The invariant that matters: **no chunk may exceed the duration ceiling**, and an
episode can never collapse into one chunk. Enforced by construction, asserted in
`segment_units`, and covered by tests from 1 to 600 input fragments including a
single unpunctuated 600-second segment with no pauses.

## Failure behaviour

Every stage fails loudly. There is no path where a failed download, a missing
ffmpeg, or an unreachable API produces plausible-looking output. A run that
cannot do the work reports what it tried and exits non-zero.

One exception, deliberate: if a single editor agent fails, the other five still
produce a usable ranking, so that degrades to a warning.

## Configuration

See `.env.example` — it documents every option. Frequently useful:

| Variable | Default | Purpose |
|---|---|---|
| `DEFAULT_LLM_PROVIDER` | `heuristic` | `openai`, `gemini`, or `heuristic` |
| `EMBEDDING_BACKEND` | `lexical` | `lexical` (offline), `openai`, `gemini` |
| `WHISPER_MODEL` | `base` | `tiny`…`large` |
| `MIN/MAX_CLIP_DURATION_SEC` | 15 / 90 | Clip length window |
| `CANDIDATE_SHORTLIST_SIZE` | 40 | Caps evaluation cost (×6 agents) |
| `RENDER_MODE` | `blur_pad` | `blur_pad` or `crop` |
| `CHECKPOINT_ENABLED` | `true` | Resume interrupted runs |

Settings are validated at startup: a provider without its key, weights that do
not sum to 1.0, or `min >= max` durations fail immediately rather than midway
through a 30-minute transcription.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

350 tests. They cover the regression cases explicitly, including the
zero-clip failure above, symmetric deduplication, cross-process embedding
determinism, and that no stage can fabricate output.

## Limitations

- **Speaker labels are not diarization.** Whisper does not diarize; caption
  tracks carry no speaker data. Labels are `Speaker_A`/`Speaker_B` heuristics
  from pauses and question marks. Use `pyannote.audio` or WhisperX for real
  diarization.
- **Named entity extraction is a heuristic**, not a trained NER model:
  capitalised runs that recur mid-sentence, plus quantities.
- **Retention and virality scores are editorial estimates**, not measured
  completion rates. Nothing here has access to platform analytics.
- **No semantic segmentation offline.** See above.
- **Word timings from caption tracks are interpolated** evenly across each cue;
  only Whisper supplies real per-word times. Caption-sourced cut adjustments are
  correspondingly approximate.
