# PROJECT_REVIEW.md

**Repository:** `podcast_into_shorts`
**Reviewed at commit:** `c395d0d` (branch `main`)
**Review date:** 2026-08-20
**Method:** Full source read plus live execution on Windows 10, Python 3.12, ffmpeg 9.0.

---

## Two corrections to the review brief

Before anything else, two premises in the review request do not match the repository. Correcting them up front, because several downstream sections depend on it.

### There is no Streamlit UI

The review asks about "Streamlit output" (§2) and "Streamlit UI" (§8). **Streamlit is not used anywhere in this project.** Verified by search across all source, requirements, and config files:

- `streamlit`, `gradio`, `flask`, `fastapi`, `django` — **zero matches** outside `.venv/`.
- `requirements.txt` contains no web framework.

The web interface is `app.py`, built on the **Python standard library** `http.server.ThreadingHTTPServer`, serving a single hand-written HTML page with vanilla JavaScript embedded as a Python string constant (`HTML_PAGE`). Section 8 documents that interface as it actually exists.

### There are no Hugging Face models

The review asks to list "every Hugging Face/API/model" (§4). **No Hugging Face model, `transformers`, `sentence-transformers`, `pyannote`, or `whisperx` dependency exists in this project.** The only match for those terms anywhere is a line in `README.md` suggesting `pyannote.audio` as a *future* option for real diarization.

The actual model inventory is in §4 and is much smaller than the question implies.

---

## 1. Complete project structure

```
podcast_into_shorts/
├── main.py                     CLI entry point. Arg parsing, provenance banner,
│                               clip printing, JSON writing, exit codes.
├── app.py                      Web dashboard (stdlib http.server). 676 lines,
│                               ~340 of which are an embedded HTML/CSS/JS string.
├── pyproject.toml              pytest + ruff + pyright config. Not a build spec.
├── requirements.txt            Core runtime deps.
├── requirements-ml.txt         Optional: openai-whisper + torch (~2 GB).
├── requirements-dev.txt        pytest, pytest-cov.
├── .env.example                Config template. NOTE: drifted from Settings (§13).
├── README.md                   User-facing docs. Some claims are stale (§13).
│
├── config/
│   └── settings.py             Single Pydantic BaseSettings class. All tunables,
│                               cross-field validation, derived embedding_dim.
│                               Exports a module-level `settings` singleton.
│
├── src/
│   ├── errors.py               Exception hierarchy. 11 classes, each carrying a
│   │                           `stage` label and an optional operator `remedy`.
│   │
│   ├── schema/
│   │   ├── clips.py            All Pydantic data models: WordTimestamp,
│   │   │                       TranscriptSegment, SentenceUnit, SemanticChunk,
│   │   │                       ExtractedFeatures, CandidateClip, ClipEvaluation,
│   │   │                       LLMClipVerdict, ClipPackaging, FinalClipOutput,
│   │   │                       DataProvenance. Range validators throughout.
│   │   └── state.py            EditorState (the LangGraph state object) plus the
│   │                           `merge_agent_evaluations` reducer and `fail()`.
│   │
│   ├── graph/
│   │   └── workflow.py         Graph assembly, edge wiring, guard/fan-out routing,
│   │                           checkpointer construction, VideoEditorPipeline.
│   │
│   ├── nodes/                  One file per graph node.
│   │   ├── _base.py            `pipeline_node` decorator: error capture, timing,
│   │   │                       `tolerant` mode for the agent branches.
│   │   ├── node_01_download.py … node_10_render.py
│   │   └── node_08_evaluate.py Builds all six agent nodes from a factory.
│   │
│   ├── providers/              External-system adapters. No business logic.
│   │   ├── ffmpeg_tools.py     Binary discovery, subprocess runner, probe_duration,
│   │   │                       probe_has_video_stream.
│   │   ├── downloader.py       yt-dlp / local file validation → MediaInfo.
│   │   ├── audio.py            16 kHz mono WAV extraction; measure_silences (UNUSED).
│   │   ├── transcriber.py      YouTube captions + Whisper + fixture loader.
│   │   ├── embeddings.py       LexicalHashingEmbedder, OpenAIEmbedder, GeminiEmbedder.
│   │   ├── vectorstore.py      Index, persist, similarity search, near-duplicate pairs.
│   │   ├── llm.py              LLMProvider: structured output, retries, disk cache.
│   │   ├── renderer.py         ffmpeg filter graphs, ASS subtitle generation.
│   │   └── trimmer.py          Fast stream-copy batch cutting from JSON timestamps.
│   │
│   ├── analysis/               Pure functions. No I/O, no external calls.
│   │   ├── segmentation.py     build_sentence_units, score_seams, segment_units.
│   │   ├── features.py         Per-chunk linguistic and timing feature extraction.
│   │   └── candidates.py       Candidate window generation + shortlisting (NMS).
│   │
│   ├── agents/
│   │   ├── editors.py          The six EditorAgent definitions, personas, prompts,
│   │   │                       LLM path and heuristic path.
│   │   └── chief_editor.py     Composite scoring, dedup, ranking, packaging.
│   │
│   ├── utils/
│   │   ├── logging_config.py   setup_logging / get_logger.
│   │   ├── metrics.py          Timestamp formatting, interval overlap geometry.
│   │   └── text_cleaner.py     Filler-word and caption-tag removal.
│   │
│   └── fixtures/
│       └── demo_transcript.json  Bundled synthetic transcript for --demo.
│
├── tests/                      18 files, ~3,050 lines, 532 tests.
│
└── (runtime, all gitignored)
    ├── cache/                  Downloaded media, extracted WAV, chunk index, LLM cache.
    ├── outputs/                final_clips.json.
    ├── renders/                Rendered MP4s and their .ass subtitle files.
    └── checkpoints/            pipeline.sqlite (LangGraph checkpoints).
```

**Scale:** ~6,640 lines of application code, ~3,050 lines of tests.

**Layering.** The separation is genuinely clean and is the project's main architectural strength:
`analysis/` is pure and testable, `providers/` wraps every external system, `nodes/` is thin glue,
`agents/` holds judgement logic, `schema/` defines the contracts. No layer reaches upward.

---

## 2. Current workflow — end to end

The flow below is what actually executes. Confirmed by running
`python main.py --source "https://www.youtube.com/watch?v=..." --render`, which completed
successfully and produced a real MP4.

### Stage 1 — YouTube URL → media file

`main.py` → `VideoEditorPipeline.run()` → `node_01_download` → `MediaDownloaderProvider.download()`

- `is_url()` checks scheme is `http`/`https` and netloc is non-empty.
- yt-dlp is invoked once with `download=True` (format `bestvideo[height<=1080]+bestaudio/best/bestaudio`),
  `ignoreerrors=False`, `noplaylist=True`, `retries=3`, and `player_client: ["mweb","android","web"]`
  as an anti-bot measure.
- Output template: `cache/%(id)s.%(ext)s`.
- The written path is recovered from `info["requested_downloads"][].filepath` (authoritative
  post-processing), falling back to `ydl.prepare_filename(info)`.
- **Duration comes from `ffprobe`**, not yt-dlp metadata. Metadata duration is used only if ffprobe fails.
- `probe_has_video_stream()` sets `media_has_video`.
- Failure raises `DownloadError`. No placeholder file is ever written.

### Stage 2 — media → 16 kHz mono WAV

`node_02_audio` → `AudioProcessorProvider.extract_audio()`

- ffmpeg: `-vn -acodec pcm_s16le -ar 16000 -ac 1` → `cache/{stem}_16k_mono.wav`.
- Result validated by `probe_duration() > 0`, not by file size.
- Skipped entirely in demo mode.

### Stage 3 — audio → transcript

`node_03_transcribe` → `TranscriberProvider.transcribe()`

Backend order, first success wins:
1. **YouTube captions** — only if `extract_youtube_id()` returns an 11-character id from a
   recognised YouTube host. Handles both `youtube-transcript-api` v1.x (`api().fetch(id)`) and
   v0.6.x (`api.get_transcript(id)`) call shapes.
2. **Local Whisper** — `whisper.load_model()` cached via `@lru_cache`, called with
   `word_timestamps=True`.

If both fail, raises `TranscriptionError` listing every attempt. **There is no fabricated fallback transcript.**

Then `build_sentence_units()` merges raw fragments into sentence-length units, flushing on a
sentence terminator, a gap ≥ 0.55 s, a speaker change, or a 20 s duration cap.

### Stage 4 — semantic processing

**`node_04_segment`** → `segment_units()`
Groups units into topic chunks. Seams are scored from: pause length (×3.0, saturating at 2 s),
sentence end (+2.0), speaker change (+1.5), discourse marker (+1.0), and — *only with an
openai/gemini embedding backend* — semantic dip (up to +3.0). A duration preference peaking at
`optimal_clip_duration_sec` is added, and the best-scoring seam inside the acceptable band is chosen.
Hard ceiling: `min(segment_max_duration_sec, max_clip_duration_sec)`.

**`node_05_index`** → `VectorStoreProvider.index_chunks()` + `.save()`
Embeds each chunk, builds a FAISS `IndexFlatIP` (or falls back to numpy matmul), persists to
`cache/chunk_index.npz` + `.meta.json`. **Non-fatal**: failure degrades to a warning and disables
semantic dedup.

**`node_06_features`** → `extract_all()`
Per chunk: emotion label/score, sentiment, named entities, speaking rate (wpm), question count,
curiosity/strong-statement/story cue scores, silence total, longest pause, keyword density,
topic confidence.

### Stage 5 — clip discovery

`node_07_candidates` → `generate_candidates()` then `shortlist_candidates()`

Candidate windows are built three ways:
1. Each chunk on its own.
2. Runs of 2–3 consecutive chunks (`MAX_MERGE_RUN = 3`).
3. Sub-windows inside any chunk longer than `min_duration × 1.4`, restricted to windows that
   begin after a sentence end and finish on one.

All filtered to `min_clip_duration_sec ≤ duration ≤ max_clip_duration_sec`. A greedy unit-walk
fallback exists if none qualify. Then `shortlist_candidates()` applies greedy non-maximum
suppression on `cheap_prescore()` down to `candidate_shortlist_size` (default 40), rejecting
anything overlapping a kept candidate by more than `shortlist_overlap_threshold` (0.55).

### Stage 6 — clip ranking

Six `node_08_*` branches run **concurrently** (real LangGraph fan-out), each scoring every
shortlisted candidate. Results merge into `agent_evaluations` via the deep-merge reducer.

`node_09_synthesize` → `synthesise()` computes the weighted composite, deduplicates, caps to
`target_clip_count_max`, and packages metadata. Full detail in §6.

### Stage 7 — final JSON

`main.py` writes `outputs/final_clips.json`:

```json
{
  "episode": "...", "duration_seconds": 0.0,
  "provenance": { "media_source": "...", "transcript_source": "...",
                  "scoring_mode": "...", "embedding_backend": "...",
                  "model_name": null, "whisper_model": null },
  "is_synthetic": false, "warnings": [],
  "clips": [ { /* full FinalClipOutput */ } ]
}
```

### Stage 8 — video rendering

`node_10_render` (only when `--render` passed) → `ClipRenderer.render()` per clip, capped at
`render_max_clips` (default 5). Full ffmpeg detail in §7.

### Stage 9 — web output (not Streamlit)

`app.py` serves the results as clip cards with embedded `<video>` players. Detail in §8.

---

## 3. LangGraph nodes

**Graph type:** `StateGraph(EditorState)`, compiled with an optional checkpointer.
**Recursion limit:** 50 (raised from the default 25 because of the fan-out).
**Routing:** every linear node is followed by a conditional edge; `_guard(next)` returns `"abort"`
if `state.error` is set. Node 7 uses `_fan_out`, which returns a **list** of all six agent node
names — LangGraph's idiom for parallel dispatch. All six branches join at node 9.

```
START → 01 → 02 → 03 → 04 → 05 → 06 → 07 ─┬→ 08_hook ──────┐
         │    │    │    │    │    │    │   ├→ 08_story ─────┤
         └────┴────┴────┴────┴────┴────┘   ├→ 08_educational┤
              all guard → abort            ├→ 08_entertain ─┼→ 09 → 10 → END
                                           ├→ 08_debate ────┤
                                           └→ 08_retention ─┘
```

### node_01_download

| | |
|---|---|
| **Input** | `state.source` / `source_url` / `input_file_path`, `state.demo_mode` |
| **Output** | Media metadata dict |
| **Responsibility** | Acquire media, establish real duration |
| **Model/API** | yt-dlp (network); ffprobe (subprocess). No AI model. |
| **Reads** | `demo_mode`, `source`, `source_url`, `input_file_path` |
| **Writes** | `podcast_title`, `media_file_path`, `duration_seconds`, `media_has_video`, `media_source`, `current_node`, `logs`, `warnings` |

Demo mode short-circuits: sets `media_source="fixture"` and acquires nothing.

### node_02_audio

| | |
|---|---|
| **Input** | `state.media_file_path` |
| **Output** | Path to 16 kHz mono WAV |
| **Responsibility** | Produce Whisper-compatible audio |
| **Model/API** | ffmpeg (subprocess). No AI model. |
| **Reads** | `demo_mode`, `media_file_path` |
| **Writes** | `audio_file_path`, `current_node`, `logs` |

### node_03_transcribe

| | |
|---|---|
| **Input** | `state.audio_file_path`, `state.source_url` |
| **Output** | Transcript segments + sentence units |
| **Responsibility** | Produce a timestamped transcript; never invent one |
| **Model/API** | `youtube-transcript-api` (HTTP), **or** OpenAI Whisper (local, `WHISPER_MODEL`, default `base`) |
| **Reads** | `demo_mode`, `audio_file_path`, `source_url`, `duration_seconds` |
| **Writes** | `transcript_segments`, `sentence_units`, `transcript_source`, `current_node`, `logs`, `warnings`, and `duration_seconds` **only if still 0** |

### node_04_segment

| | |
|---|---|
| **Input** | `state.sentence_units` |
| **Output** | List of `SemanticChunk` |
| **Responsibility** | Divide the episode into topic chunks |
| **Model/API** | Embedding backend **only if** `EMBEDDING_BACKEND` is `openai`/`gemini`. Default `lexical` = no API. |
| **Reads** | `sentence_units` |
| **Writes** | `semantic_chunks`, `current_node`, `logs` |

⚠️ Force-split units created inside `segment_units()` are **not** written back to
`sentence_units`. See §13, TP-4.

### node_05_index

| | |
|---|---|
| **Input** | `state.semantic_chunks` |
| **Output** | Index count + persisted path |
| **Responsibility** | Embed and persist chunk vectors |
| **Model/API** | `LexicalHashingEmbedder` (BLAKE2b, offline, default), or `text-embedding-3-small` / `models/text-embedding-004` |
| **Reads** | `semantic_chunks` |
| **Writes** | `indexed_chunk_count`, `index_path`, `current_node`, `logs`, `warnings` |

Failure is **non-fatal** by design — returns `indexed_chunk_count=0` and a warning.

### node_06_features

| | |
|---|---|
| **Input** | `state.semantic_chunks`, `state.sentence_units` |
| **Output** | `{chunk_id: ExtractedFeatures}` |
| **Responsibility** | Measure linguistic and timing signals |
| **Model/API** | None. Pure regex/statistics. |
| **Reads** | `semantic_chunks`, `sentence_units` |
| **Writes** | `extracted_features`, `current_node`, `logs` |

### node_07_candidates

| | |
|---|---|
| **Input** | units, chunks, features |
| **Output** | Shortlisted `CandidateClip` list |
| **Responsibility** | Generate windows, cap evaluation cost |
| **Model/API** | None. |
| **Reads** | `sentence_units`, `semantic_chunks`, `extracted_features` |
| **Writes** | `candidate_clips`, `current_node`, `logs`, `warnings` |

### node_08_{hook,story,educational,entertainment,debate,retention}

Six structurally identical nodes from `make_agent_node(agent)`. All `tolerant=True` — a failure
becomes a warning, not an abort, so five agents still yield a usable ranking.

| | |
|---|---|
| **Input** | `state.candidate_clips`, `state.duration_seconds` |
| **Output** | `{clip_id: {agent_key: ClipEvaluation}}` |
| **Responsibility** | Score every candidate from one editorial perspective |
| **Model/API** | `gpt-4o-mini` (default) or `gemini-3.6-flash` via `with_structured_output(LLMClipVerdict)` — **only if `DEFAULT_LLM_PROVIDER` is set with a key.** Otherwise pure heuristic, no API. |
| **Reads** | `candidate_clips`, `duration_seconds` |
| **Writes** | `agent_evaluations` (**merged**, not replaced), `logs`, `warnings` |

Each node opens its own `ThreadPoolExecutor(max_workers=llm_max_concurrency)`. See §13, TP-2.

| Node | Authoritative metric | Composite weight |
|---|---|---|
| `node_08_hook` | `hook_strength` | 0.25 |
| `node_08_debate` | `comment_potential` | 0.20 |
| `node_08_educational` | `educational_value` | 0.20 |
| `node_08_retention` | `watch_time_prediction` | 0.20 |
| `node_08_story` | `story_completeness` | 0.15 |
| `node_08_entertainment` | `entertainment` | **0.00 — context only** |

### node_09_synthesize

| | |
|---|---|
| **Input** | `candidate_clips`, `agent_evaluations`, `index_path` |
| **Output** | Ranked, deduplicated, packaged `FinalClipOutput` list |
| **Responsibility** | Chief editor: composite score, dedup, cap, package |
| **Model/API** | Optionally the LLM again for `ClipPackaging`. Reloads the vector index for near-duplicate pairs. |
| **Reads** | `candidate_clips`, `agent_evaluations`, `podcast_title`, `index_path`, `media_source`, `transcript_source` |
| **Writes** | `final_clips`, `scoring_mode`, `current_node`, `logs`, `warnings` |

`scoring_mode` reflects **what actually happened** — if every agent fell back to heuristics, it
records `heuristic` even when an LLM was configured.

### node_10_render

| | |
|---|---|
| **Input** | `final_clips`, `media_file_path`, `transcript_segments` |
| **Output** | Rendered MP4 paths |
| **Responsibility** | Cut, reframe to 9:16, burn captions, normalise audio |
| **Model/API** | ffmpeg (subprocess). No AI model. |
| **Reads** | `render_requested`, `demo_mode`, `media_file_path`, `final_clips`, `transcript_segments`, `sentence_units`, `media_has_video` |
| **Writes** | `rendered_files`, `final_clips` (mutated with `rendered_file_path`), `current_node`, `logs`, `warnings` |

Per-clip failure degrades to a warning; the JSON recommendations survive.

### abort

Terminal node reached from any guard when `state.error` is set. Writes `current_node="ABORTED"`
and one log line.

---

## 4. AI models actually in use

**No Hugging Face models. No `transformers`. No local embedding model. No diarization model.**

| Model | Where | Purpose | Default? |
|---|---|---|---|
| **OpenAI Whisper** (`base`) | `transcriber.py:_from_whisper` | Local speech-to-text with word timestamps | ⚠️ Optional — needs `requirements-ml.txt` (~2 GB torch). **Not installed by default.** |
| **`gpt-4o-mini`** | `editors.py`, `chief_editor.py` | Agent scoring (`LLMClipVerdict`) and clip packaging (`ClipPackaging`) | ❌ Off. Needs `DEFAULT_LLM_PROVIDER=openai` + key. |
| **`gemini-3.6-flash`** | same | Same, Gemini path | ❌ Off. Needs `DEFAULT_LLM_PROVIDER=gemini` + key. |
| **`text-embedding-3-small`** (1536-d) | `embeddings.py:OpenAIEmbedder` | Chunk embeddings → semantic segmentation + near-duplicate detection | ❌ Off. Needs `EMBEDDING_BACKEND=openai`. |
| **`models/text-embedding-004`** (768-d) | `embeddings.py:GeminiEmbedder` | Same, Gemini path | ❌ Off. |
| **`LexicalHashingEmbedder`** | `embeddings.py` | **Not a model.** BLAKE2b hashing vectoriser (512-d) over word unigrams, bigrams and 4-char n-grams with sublinear TF. | ✅ **This is the default.** |

### What this means

**Out of the box, this project uses no AI model at all.** The default configuration
(`DEFAULT_LLM_PROVIDER=heuristic`, `EMBEDDING_BACKEND=lexical`, no Whisper installed) runs a
fully deterministic pipeline: YouTube captions for text, regex/statistics for features, hand-tuned
arithmetic for scoring, and a hashing vectoriser for similarity.

The repo is explicit and honest about this — output is stamped `scoring_mode="heuristic"` and both
the CLI and dashboard display a warning. But it is the single most important fact about the
system's current capability: **the "six AI editor agents" are, by default, six weighted arithmetic
formulas over measured text features.**

The `LexicalHashingEmbedder` deserves a specific note. It measures *lexical overlap*, not meaning —
it cannot see that "car" and "automobile" are related. `node_04_segment` therefore **deliberately
disables semantic dip detection** for it, on the documented basis that measurement showed it does
not separate topics at any window size from 2 to 10 units.

---

## 5. Prompts

All model-facing prompts live in two files.

### 5.1 Base system prompt — `editors.py:BASE_SYSTEM`

```
You are part of a team selecting short vertical clips (YouTube Shorts,
TikTok, Reels) from long-form podcast and interview transcripts.
Rate strictly on a 0-10 scale where 5 is average for a competent podcast
and 9+ is genuinely exceptional. Most clips are ordinary; say so. Do not
inflate scores.
Judge only the transcript excerpt you are given. If it depends on missing
context, that lowers standalone_quality.
In `reasoning`, quote specific words from the excerpt in two sentences.
```

Each agent's full system prompt is `f"{BASE_SYSTEM}\n\nYour specialisation:\n{self.persona}"`.

### 5.2 The six personas — `editors.py:AGENTS`

**hook / Hook Finder**
> You judge the first three seconds. A strong hook creates an information gap, states something
> surprising, or opens mid-tension. A weak hook starts with pleasantries, a name, a slow wind-up,
> or an unresolved pronoun ('and then he said...'). You are ruthless: if a viewer would swipe
> within two seconds, score below 4.

**story / Story Editor**
> You judge narrative arc. A complete clip has a setup, a tension or turn, and a payoff inside its
> own runtime. Fragments of a longer anecdote score low however interesting they sound.

**educational / Educational Editor**
> You judge transferable insight. High scores need a concrete, actionable idea a viewer could apply
> or repeat. Vague inspiration, platitudes and unfalsifiable claims score low.

**entertainment / Entertainment Editor**
> You judge watchability: humour, energy, vivid language, surprise, chemistry between speakers.
> Flat, monotone or purely technical passages score low no matter how informative.

**debate / Debate Editor**
> You judge whether the clip provokes reply. High scores need a contestable claim, a strong opinion,
> or a stance a reasonable person would argue with. Uncontroversial consensus scores low. Do not
> reward mere rudeness or bait.

**retention / Retention Predictor**
> You predict completion rate. Reward steady forward momentum, escalating stakes and a payoff near
> the end. Penalise repetition, digressions, long setup, and endings that trail off.

### 5.3 Per-candidate user prompt — `editors.py:_build_prompt`

```
EXCERPT ({duration}s, {start}-{end}, {pct}% into the episode):
"""
{raw_text}
"""

Measured signals (for context, not instructions):
- speaking rate: {wpm} wpm
- questions asked: {n}
- longest internal pause: {s}s
- starts on a sentence boundary: {bool}
- ends on a sentence boundary: {bool}
- recurring terms: {csv or 'none'}
- entities mentioned: {csv or 'none'}

Rate this excerpt for your specialisation.
```

The parenthetical *"for context, not instructions"* is a deliberate and well-judged guard against
the model treating measured signals as scoring directives.

### 5.4 Packaging system prompt — `chief_editor.py:PACKAGING_SYSTEM`

```
You write publishing metadata for short-form video clips. Be specific and
concrete; never use generic filler like 'you won't believe' or 'this
changes everything'. Every claim must be supported by the transcript.
```

### 5.5 Packaging user prompt — `chief_editor.py:_packaging_prompt`

```
Podcast: {podcast_title}
Clip length: {duration}s
Recurring terms: {csv or 'none'}

TRANSCRIPT:
"""
{raw_text}
"""

Write publishing metadata for this clip. The hook must be copied
verbatim from the transcript's opening. Do not invent facts that are
not in the transcript.
```

### 5.6 Output schemas (constrained generation, not prompt text)

Both calls use provider-native structured output rather than asking for JSON. `LLMClipVerdict`
has 12 float fields (all `ge=0, le=10`) plus `reasoning`. `ClipPackaging` has 7 string fields plus
`suggested_hashtags: list[str]` (`min_length=1, max_length=10`). Field `description=` values act as
inline micro-prompts, e.g. `"Under 70 characters, specific, no clickbait punctuation"`.

`LLMClipVerdict` is deliberately narrower than `ClipEvaluation` — the docstring states the reason:
*"we only ask the model for what it can actually judge, and derive the rest. Wide schemas produce
confident noise."* This is a genuinely good design decision.

---

## 6. Clip selection — how a moment becomes a Short

Five sequential filters. A moment must survive all of them.

### Filter 1 — structural eligibility (`candidates.py:generate_candidates`)

A window must fall within `[MIN_CLIP_DURATION_SEC, MAX_CLIP_DURATION_SEC]` (default 15–90 s).
Sub-window candidates additionally must begin after a sentence terminator and end on one.

### Filter 2 — cheap prescore + NMS (`candidates.py:cheap_prescore`)

Model-free triage deciding where to spend evaluation budget:

```
score  = max(0, 1 - |1 - duration/optimal|) × 3.0     # triangular, peaks at 45 s
       + 2.0  if starts_on_sentence_boundary
       + 2.0  if ends_on_sentence_boundary
       + min(lead_in_silence_sec,  1.0)
       + min(lead_out_silence_sec, 1.0)
       + curiosity_score        × 1.5
       + strong_statement_score × 1.5
       + story_likelihood       × 1.5
       + min(question_count, 3) × 0.3
       - 2.0  if words/duration×60 < 80 wpm           # sparse-speech penalty
```

Greedy non-maximum suppression keeps the top 40, rejecting anything overlapping a kept candidate
by more than 0.55 (intersection-over-shorter).

### Filter 3 — six-agent evaluation

**LLM mode:** each agent returns an `LLMClipVerdict`. Per-agent `overall_score` is a weighted blend
where the focus metric carries 0.5 and two context metrics 0.25 each. `virality_score` is derived
uniformly across all agents as `shareability×0.4 + comment_potential×0.3 + hook_strength×0.3`.

**Heuristic mode (default)** — every number is a transformation of a measured feature. Examples:

```
hook = 3.0 + curiosity×3.0 + strong_statement×2.0
       + 1.0 if "?" in first sentence
       + 1.0 if starts_on_sentence_boundary
       - 2.5 if DANGLING_START_RE matches   # "and", "so", "he", "this"...
watch_time = 4.0 + rate_fit×3.5 + clean_edges×0.75 - silence_penalty
             where rate_fit = 1 - min(1, |wpm - 150|/100)
confidence = 3.0 + topic_confidence×2.5 + clean_edges×0.75
```

All clamped to [0, 10]. The dangling-opener penalty is the sharpest signal here — it directly
targets clips that cannot stand alone.

### Filter 4 — composite score (`chief_editor.py:composite_score`)

```
composite = hook.hook_strength              × 0.25
          + debate.comment_potential        × 0.20
          + educational.educational_value   × 0.20
          + retention.watch_time_prediction × 0.20
          + story.story_completeness        × 0.15
```

Each agent contributes **only its authoritative metric**. Weights validated to sum to 1.0 at startup.
**Note: the entertainment agent contributes nothing to the composite** — it runs, costs an LLM call
per candidate, and its verdict reaches the JSON but never influences ranking.

### Filter 5 — deduplication and cap (`chief_editor.py:deduplicate`)

Sorted by `(-composite, start_time)`, then two independent duplicate checks against already-kept clips:

1. **Time overlap** — intersection-over-*shorter* > `DEDUP_OVERLAP_THRESHOLD` (0.5). Using the
   shorter interval makes containment always score 1.0, so a long clip cannot smuggle in an
   already-published short one.
2. **Semantic near-duplication** — chunk pairs with cosine ≥ `NEAR_DUPLICATE_SIMILARITY` (0.88),
   from the persisted index. Catches the same point restated later, which time overlap cannot see.

Survivors are capped at `TARGET_CLIP_COUNT_MAX`. Falling below `TARGET_CLIP_COUNT_MIN` emits a warning.

### Reported scores

- `overall_score` = the composite above.
- `virality_score` = **mean** across all six agents.
- `confidence_score` = mean self-reported confidence **minus** the standard deviation of the agents'
  overall scores (capped at 3.0). Disagreement lowers confidence. This is a nice touch.
- `viewer_retention_prediction` = a **label** (`High`/`Moderate`/`Uncertain`/`Low`) plus the raw
  score. The code explicitly refuses to render a 0–10 score as a fake completion percentage.

### Cut-point adjustment

```
start_adj = -min(0.6, lead_in_silence  × 0.5)   if lead_in  > 0.1 else 0
end_adj   = +min(0.5, lead_out_silence × 0.5)   if lead_out > 0.1 else 0
```

Derived from real measured pauses, with a per-clip textual rationale.

---

## 7. Video generation — yes, it works

**The project genuinely produces publishable MP4 files.** Verified by execution:

```
Rendering clip_01 (17.7s, 14 caption cues)
→ renders/clip_01.mp4

ffprobe: width=1080  height=1920  duration=17.733333
```

Real 9:16 vertical video with burned-in captions. This is not a stub.

### The ffmpeg pipeline (`renderer.py`)

**Step 1 — caption cues.** `build_caption_cues()` selects word timestamps overlapping the clip,
groups them into cues of ≤ 3 words or ≤ 2.5 s, and rebases times to clip-relative.

**Step 2 — ASS subtitle file.** Written next to the output. Style is computed from output height:
font size `max(28, height×0.038)`, bottom margin `height×0.16`, side margins `width×0.07`, white
fill with dark outline, `WrapStyle: 2`.

**Step 3 — seek and trim.**
```
ffmpeg -y -hide_banner -accurate_seek -ss {start} -t {duration} -i {source}
```
`-ss` before `-i` for fast seeking; `-accurate_seek` for frame accuracy (valid here because this
path re-encodes).

**Step 4 — filter graph.** Two modes:

*`blur_pad` (default)* — keeps the whole 16:9 frame visible against a blurred fill:
```
[0:v]split=2[bg][fg];
[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=28[bgb];
[fg]scale=1080:-2:force_original_aspect_ratio=decrease[fgs];
[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1[v]
```

*`crop`* — fills the frame but can cut faces out of an interview shot:
```
[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[v]
```

*Audio-only sources* get a synthetic background plus an animated waveform:
```
-f lavfi -t {duration} -i color=c=0x0B0F19:s=1080x1920:r=25
[0:a]showwaves=s=1080x345:mode=cline:rate=25:colors=0x6366F1[wave];
[1:v][wave]overlay=0:(H-h)/2:shortest=1,setsar=1[v]
```

Then captions are chained: `[v]subtitles='{escaped_path}'[vout]`, or `[v]null[vout]` if none.

**Step 5 — encode.**
```
-map [vout] -map 0:a?
-af loudnorm=I=-14:TP=-1.5:LRA=11     # -14 LUFS = platform standard
-c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p
-c:a aac -b:a 160k
-movflags +faststart
```

`-14 LUFS`, `yuv420p` and `+faststart` are all correct choices for social platforms.

**Step 6 — verify.** Raises `RenderError` if the output is missing or zero bytes.

### The separate fast-trim path (`trimmer.py`)

An independent subsystem for cutting clips from JSON timestamps without re-running analysis:
```
ffmpeg -y -accurate_seek -ss {start} -t {duration} -i {source}
       -c copy -avoid_negative_ts make_zero {out}
```
Stream copy, sub-second. **Caveat not documented in the code:** `-c copy` can only cut on
keyframes, so the real start drifts to the preceding keyframe — commonly 2–10 s on YouTube
downloads. `-accurate_seek` has no effect in copy mode.

### What is missing from rendering

- **No B-roll, zoom, or motion.** Static reframe only.
- **No speaker-aware framing.** No face detection, so `crop` mode can cut a speaker out of frame.
- **No karaoke/word-highlight captions.** Cues appear as static 3-word groups; the current
  short-form convention is per-word highlighting.
- **No intro/outro, logo, or progress bar.**
- **Captions unavailable via the trimmer's full-render mode** — it passes `units=[], all_words=[]`.
- **Renders fail on any path containing an apostrophe** (§13, TP-3).

---

## 8. Web UI — `app.py` (NOT Streamlit)

**Technology:** Python stdlib `ThreadingHTTPServer` + `BaseHTTPRequestHandler`. The entire
frontend is a single HTML string constant with inline CSS and vanilla JS. No build step, no npm,
no framework, no external CDN (deliberately — the Google Fonts link was removed to preserve
offline operation).

**Routes**

| Method | Path | Purpose |
|---|---|---|
| GET | `/`, `/index.html` | The dashboard page |
| GET | `/health` | `{status, scoring_mode, embedding_backend}` |
| GET | `/api/status?job_id=` | Poll job state (client polls every 800 ms) |
| GET | `/renders/{filename}` | Serve MP4 with HTTP Range support |
| POST | `/api/analyze` | Start analysis; returns `job_id`, 202 |
| POST | `/api/trim` | Batch-trim from JSON clips; returns `job_id`, 202 |

**Input controls:** a text field (YouTube URL or local path), a "Demo mode" checkbox, a "Render"
checkbox, a "Fast cut" checkbox, an analyse button and a "Trim all" button.

### What the user sees after analysis

**During the run:** a live log panel, appended from `job.logs` on each poll. Log lines come from a
custom `ThreadJobLogHandler` attached to the root logger.

**Banners, when applicable:**
- Red — *"Synthetic fixture data — these results do not describe real media. Do not publish them."*
- Amber — *"Scored without a language model. Rankings come from measured signals only and are a weak proxy for editorial judgement."*
- Amber list of pipeline warnings.

**One card per clip, containing:**
1. Rank badge (`#1`, `#2`, …)
2. Title
3. `MM:SS - MM:SS (NN.Ns)`
4. **Hook** line
5. **Embedded `<video controls>` player** — only when `rendered_file_path` is set
6. **"⬇ Download Short (MP4)"** button
7. Metric rows: Overall `N.NN / 10`, Virality, Confidence, Retention label, Cut adjust
8. One-sentence summary and "Why:" rationale
9. Absolute rendered file path
10. Hashtag chips

**On failure:** a red banner — *"Failed at stage '{stage}': {error}"* — plus any warnings.

**XSS note:** the client builds DOM nodes and assigns `textContent` rather than `innerHTML`, so a
transcript or title containing markup cannot execute. This was a deliberate fix and is correctly done.

### What the UI does not have

No persistence across restarts (jobs live in an in-memory dict), no job history, no authentication,
no way to edit clip boundaries, no re-render of a single clip, no batch export beyond individual
downloads, no progress percentage (log lines only), no mobile-responsive layout.

---

## 9. Database / vector store

**There is no database.** No SQL schema, no ORM, no migrations. The only SQLite file is
`checkpoints/pipeline.sqlite`, owned entirely by LangGraph for state checkpointing.

**Vector search is implemented and does run.** `src/providers/vectorstore.py`:

- `index_chunks()` embeds all chunk texts and stores an L2-normalised `float32` matrix.
- Backend: **FAISS `IndexFlatIP`** if `faiss-cpu` imports, else a **numpy matmul** fallback.
  Identical results on normalised vectors — inner product equals cosine similarity.
- `save()` writes `cache/chunk_index.npz` (compressed vectors) + `cache/chunk_index.meta.json`
  (dimension, embedder name, chunk ids, chunk texts).
- `load()` restores it in `node_09_synthesize`.

**What it is actually used for:** exactly one thing — `find_near_duplicates(threshold=0.88)`,
computing the full `vectors @ vectors.T` similarity matrix and returning pairs above threshold, so
the chief editor can drop a clip that restates an already-selected point elsewhere in the episode.

**What is implemented but unused:** `similarity_search(query, k)` has **no production callers** —
only tests. Its own module docstring lists "had no callers at all" as a *fixed* defect; it is
still uncalled.

**Important qualification.** With the default `EMBEDDING_BACKEND=lexical`, the vectors encode
*lexical overlap*, not meaning. Near-duplicate detection at 0.88 will catch near-verbatim repetition
but will not catch the same idea expressed in different words. Genuine semantic dedup requires
`EMBEDDING_BACKEND=openai` or `gemini`.

**Concurrency defect:** the index path is a fixed constant, so parallel dashboard jobs overwrite
each other's index (§13, TP-6).

---

## 10. File storage

All runtime directories are created by `settings.ensure_directories()` at entry-point startup —
never as an import side effect. All four are gitignored.

| Artifact | Location | Naming | Cleanup |
|---|---|---|---|
| Downloaded media | `cache/` | `{youtube_id}.{ext}` (yt-dlp `outtmpl`) | ❌ Never |
| Extracted audio | `cache/` | `{stem}_16k_mono.wav` | ❌ Never — and **collides across episodes with the same filename** (§13, TP-5) |
| Chunk vectors | `cache/chunk_index.npz` | Fixed name | ❌ Overwritten each run |
| Chunk metadata | `cache/chunk_index.meta.json` | Fixed name | ❌ Overwritten |
| LLM response cache | `cache/llm_cache/{sha256[:32]}.json` | Content hash of provider+model+schema+prompt | ❌ Never; unbounded |
| Final JSON | `outputs/final_clips.json` | `--output` flag, path-traversal validated | ❌ Overwritten |
| Rendered MP4s | `renders/{clip_id}.mp4` | Sanitised clip id | ❌ Never |
| Fast-trim MP4s | `renders/{clip_id}_fast.mp4` | Sanitised + `_fast` | ❌ Never |
| Subtitles | `renders/{clip_id}.ass` | Beside the MP4; **left on disk** | ❌ Never |
| Checkpoints | `checkpoints/pipeline.sqlite` (+ `-wal`, `-shm`) | One row-set per `thread_id` | ❌ Never |
| Transcripts | **Not persisted** | — | — |
| Whisper weights | `~/.cache/whisper/` (managed by the library) | — | — |

**Transcripts are never written to disk.** They exist only inside `EditorState` — and therefore
inside the checkpoint blob when checkpointing is on. Re-running a source re-fetches captions or
re-runs Whisper unless the checkpoint is reused.

**There is no cleanup or retention policy anywhere.** `cache/`, `renders/`, `checkpoints/` and
`cache/llm_cache/` all grow without bound. For a service processing full-length podcasts this is
a real operational problem — a single 2-hour episode leaves the source download plus a 16 kHz WAV
in `cache/` permanently.

---

## 11. Current features — verified checklist

Everything below was confirmed either by reading the implementation or by executing it.

**Ingestion**
- [x] YouTube download via yt-dlp with anti-bot player-client fallbacks
- [x] Local media file support (15 recognised extensions)
- [x] Real duration via ffprobe; never a placeholder
- [x] Video-stream detection
- [x] Cookie support for gated content — ⚠️ *implemented but broken*, see TP-9
- [x] 16 kHz mono WAV extraction with probe-based validation

**Transcription**
- [x] YouTube caption fetch, supporting both v0.6.x and v1.x API shapes
- [x] Host-anchored YouTube ID extraction (rejects local paths and other domains)
- [x] Local Whisper with word timestamps — ⚠️ *optional dep, not installed by default*
- [x] Fragment → sentence-unit merging on terminator / pause / speaker / duration cap
- [x] Filler-word and caption-tag cleaning
- [x] Heuristic speaker turn labelling (honestly named `Speaker_A`/`Speaker_B`)
- [x] Bundled fixture transcript for `--demo`

**Analysis**
- [x] Pause/punctuation/speaker-turn topic segmentation with hard duration ceiling
- [x] Optional semantic dip detection (openai/gemini backends only)
- [x] Feature extraction: entities, percentages, quantities, cue families, speaking rate, pauses
- [x] Three-strategy candidate generation + greedy NMS shortlisting
- [x] Deterministic offline embedding (BLAKE2b — stable across processes)
- [x] FAISS index with numpy fallback
- [x] Semantic near-duplicate detection
- [x] Symmetric time-overlap dedup (intersection-over-shorter)

**Scoring**
- [x] Six parallel agent branches as real graph nodes
- [x] LLM scoring via provider-native constrained structured output
- [x] Complete heuristic fallback mode — every metric derived from a measurement
- [x] Weighted composite scoring, validated to sum to 1.0
- [x] Disagreement-penalised confidence
- [x] Per-clip cut adjustment from measured silence

**Output**
- [x] Structured JSON with full provenance
- [x] **Real 1080×1920 MP4 rendering with burned captions** — verified end to end
- [x] blur_pad and crop reframing modes
- [x] Audio-only rendering with animated waveform
- [x] Loudness normalisation to −14 LUFS
- [x] Fast stream-copy batch trimming from JSON
- [x] Web dashboard with live logs, clip cards, embedded players, MP4 download
- [x] HTTP Range support for video seeking

**Engineering**
- [x] Typed, cross-validated settings with startup failure on invalid config
- [x] Structured exception hierarchy with operator remedies
- [x] Provenance stamped end to end
- [x] LangGraph checkpointing for resumable runs
- [x] On-disk LLM response cache
- [x] 532 passing tests
- [x] Path-traversal protection on `--output` and `/renders/`
- [x] XSS-safe DOM construction in the dashboard

---

## 12. Missing features

**Referenced in code or docs but not implemented**
- [ ] `cache/synthetic_demo.mp4` — referenced in 3 places, created by nothing. `--demo --trim-json` is a dead path.
- [ ] `measure_silences()` — full ffmpeg `silencedetect` implementation, **zero callers**. The "measured pauses" the README advertises come from transcript gaps, not acoustics.
- [ ] `similarity_search()` — no production callers.
- [ ] `timestamp_to_seconds()`, `intersection_over_union()`, `format_duration()` — tested, unused.
- [ ] `enable_diarization` setting exists in `Settings`; nothing reads it.
- [ ] `segment_similarity_drop` setting exists; nothing reads it.

**Documented as future work**
- [ ] Real speaker diarization (`pyannote.audio` / WhisperX)
- [ ] Trained NER instead of the capitalised-run heuristic
- [ ] Offline semantic segmentation

**Absent for the stated product goal**
- [ ] Face detection / speaker-aware reframing
- [ ] Word-highlight (karaoke) captions
- [ ] B-roll, zoom, motion, intro/outro, branding
- [ ] Direct publishing to YouTube/TikTok/Instagram
- [ ] Manual clip boundary editing in the UI
- [ ] Multi-episode / batch queue
- [ ] Job persistence across restarts
- [ ] Authentication or multi-tenancy
- [ ] Storage retention / cleanup policy
- [ ] Cost estimation or budget cap before an LLM run
- [ ] Aspect-ratio options beyond 9:16
- [ ] Thumbnail image generation (text is suggested; no image produced)
- [ ] A/B title or hook variants
- [ ] Any feedback loop from published performance

**Missing infrastructure**
- [ ] CI — no `.github/`, no pre-commit, no Makefile
- [ ] Ruff enforcement — configured in `pyproject.toml`, 37 violations outstanding
- [ ] Dockerfile / deployment story
- [ ] Structured metrics or tracing

---

## 13. Technical problems

Ordered by severity. All reproduced.

### TP-1 · CRITICAL — the default configuration crashed on every entry point

`src/graph/workflow.py:96`. `SqliteSaver.from_conn_string(db).__enter__()` entered a
`@contextmanager` generator without retaining a reference. GC ran its `finally`, closing the
connection before first use:

```
sqlite3.ProgrammingError: Cannot operate on a closed database.
```

**This affected `main.py --demo`, `main.py --source`, and `app.py` alike** — the project was
unusable out of the box. A one-line fix (own the `sqlite3.connect()` directly, with
`check_same_thread=False` since LangGraph uses worker threads) resolves it.

**The deeper defect is the test gap:** every pipeline test passes `use_checkpointer=False`. The
default — the only value real users get — was exercised by nothing except two `TestCLIExitCodes`
tests, which were the two failing.

### TP-2 · HIGH — LLM concurrency runs at 6× the configured limit

`node_08_evaluate.py:41-43`. Each of the six agent nodes opens its own
`ThreadPoolExecutor(max_workers=llm_max_concurrency)`, and LangGraph runs all six concurrently.
Measured: **36 simultaneous in-flight calls with the setting at 6.** The code comment claims
"Bounded by llm_max_concurrency to respect rate limits." Fix: one shared module-level `Semaphore`
inside `LLMProvider`.

### TP-3 · HIGH — rendering fails on any path containing an apostrophe

`renderer.py:59-70`. `escape_filter_path` emits `\'`, but the result is interpolated into a
single-quoted ffmpeg filter argument where backslash escaping does not apply. The quote terminates
early and the rest of the graph — including the `[vout]` pad label — is absorbed into the filename:

```
Unable to open .../My Podcasts Folder/out/clip.ass[vout]
Error initializing filters
```

Spaces and commas are fine; only `'` breaks. Correct escape inside single quotes is `'\''`.

### TP-4 · HIGH — force-split units never reach the candidate stage

`segmentation.py:252-258`. `segment_units()` splits over-long units into a local `expanded` list
and builds chunks from it, but returns only the chunks. `state.sentence_units` keeps the unsplit
list, so `chunk_unit_ranges()` maps N+k chunks onto N units and indexes past the end:

```
chunks: [chunk_001 0-15, chunk_002 15-30, chunk_003 30-45]
ranges: [(0,0), (1,1), (2,2)]     # units[2] does not exist
→ IndexError: list index out of range
```

Not reachable on defaults (units cap at 20 s, chunk ceiling is 90 s) but becomes live the moment
anyone sets `MAX_CLIP_DURATION_SEC` below 20 — a valid config.

### TP-5 · HIGH — audio cache collides across episodes

`audio.py:36`. Cached as `{stem}_16k_mono.wav`. Two shows both named `episode.mp3` share one file;
the second hits the reuse check, logs "Reusing cached audio", and transcribes the **first**
episode — producing a complete, confident, entirely wrong result. Key on a hash of resolved path +
size + mtime.

### TP-6 · HIGH — concurrent jobs share one chunk index

`vectorstore.py:146` always writes `cache/chunk_index.npz`. The dashboard runs jobs in parallel
threads, so job A can deduplicate against job B's episode.

### TP-7 · HIGH — a failed run poisons its thread id permanently

`error` and `failed_stage` are checkpointed channels. Re-invoking the same `thread_id` restores
them and `_guard` routes straight to `abort` before any node runs. Reproduced: a valid `--demo`
reported a previous run's download error. `--thread-id` defaults to `cli`.
`logs`/`warnings` use `operator.add` and likewise accumulate across runs.

### TP-8 · MEDIUM — every failed run is labelled synthetic fixture data

`state.py:105-122`. `provenance()` does `media_source or "fixture"`. Those fields are `None` until
their stage succeeds, so a real MP4 that failed at transcription printed:

```
Provenance : [SYNTHETIC FIXTURE DATA] media=local_file transcript=fixture
!! SYNTHETIC DATA: these results describe a bundled fixture, not real media.
```

This is precisely the mislabelling the provenance system exists to prevent.

### TP-9 · MEDIUM — cookie support is broken

`downloader.py:142`. yt-dlp unpacks `cookiesfrombrowser` as a 4-tuple. Passing the string
`"chrome"` unpacks character-by-character:
`TypeError: takes from 1 to 4 positional arguments but 6 were given`. Confirmed against yt-dlp
2026.7.4. This matters because cookies are the standard fix for the YouTube bot checks the
downloader already tries to work around.

### TP-10 · MEDIUM — non-retryable errors are retried with backoff

`llm.py:132-152` catches bare `Exception` and retries everything. A 401 or 404 model name will
never succeed, yet burns 4 attempts with 1+2+4 s of sleep. At 40 candidates × 6 agents that is
roughly 70 minutes of sleeping before the user learns the key is wrong.

### TP-11 · MEDIUM — malformed Range header returns no HTTP response

`app.py:544-580`. Unvalidated `int()` inside a bare `except Exception` that logs and returns
without writing a status line. Measured:

```
Range: bytes=0-99        → 206, 100 bytes    ok
Range: bytes=abc-def     → empty reply (curl 52)
Range: bytes=0-10,20-30  → empty reply (curl 52)
Range: bytes=99999999-   → 206 with 0 bytes  (should be 416)
```

### TP-12 · MEDIUM — cross-job log contamination

`app.py:352`. `ThreadJobLogHandler` attaches to the **root** logger with no thread or job filter.
Proven: one log record from one job landed in both jobs' log streams. With concurrent users, each
sees the others' source URLs and file paths.

### TP-13 · MEDIUM — unbounded resource growth in the server

Three leaks in one path: `_jobs` retains every job's full clip payload forever; each job constructs
a new `VideoEditorPipeline()` opening a new SQLite connection that is never closed; and
`thread_id=job_id` (a fresh UUID) adds a permanent checkpoint thread per analysis while making
resumability — the entire reason checkpointing exists — unavailable to the dashboard.

*(Observed live: two orphaned `app.py` processes still held `pipeline.sqlite` open long after use.)*

### TP-14 · MEDIUM — text cleaner capitalises every word

`text_cleaner.py:51` ends with "capitalise the first character" — correct for a sentence, but
`transcriber.py:245` calls it **per word** when building word timings:

```
'the' → 'The'    'brown' → 'Brown'    'iPhone' → 'IPhone'
```

Burned captions read "The Quick Brown Fox". Also `\ber+\b` deletes the real word "err", and
`segment.text` and `segment.words` can disagree.

### TP-15 · MEDIUM — the trimmer silently substitutes the wrong media

`trimmer.py:137-155`. When a path fails to resolve it falls back to `synthetic_demo.mp4`, then to
**any** media file in `cache/` chosen by newest mtime. A typo yields clips cut from an unrelated
episode with the requested titles and no error — contradicting the project's own stated principle.

### TP-16 · LOW — assorted

- `except json.JSONDecodeError` after `except ValueError` is dead code (`JSONDecodeError` subclasses `ValueError`). Confirmed: malformed JSON returns the raw decoder message.
- `--fast` is `action="store_true", default=True` — it can never be `False`.
- `probe_has_video_stream` matches the attached-picture stream in any MP3 with cover art.
- Trimmer full-render mode passes `units=[], all_words=[]` — captions can never burn.
- `adjusted_end_seconds` is never clamped to media duration, and the model validator does not check the adjusted pair.
- Stream-copy trimming is keyframe-bound, not frame-accurate, and the docstring does not say so.
- `.env.example` still ships `GEMINI_MODEL=gemini-1.5-flash` — the deprecated model commit `3947af9` specifically fixed in `settings.py` to stop 404s — while the README instructs `cp .env.example .env`.
- Blank `TRANSCRIPT_LANGUAGE=` becomes `""`, not `None`; Whisper auto-detects only on `None`.
- 19 `Settings` fields are undocumented in `.env.example`, including all five scoring weights.

### Architectural observations

**Unnecessary complexity.** The trimmer duplicates media resolution and clip-model construction
that `renderer.py` already does. Two independent cutting paths with different semantics
(frame-accurate re-encode vs keyframe-bound copy) is a maintenance liability, and it is where two
of the worst data-integrity bugs live.

**Performance.** `find_near_duplicates` materialises a full `n × n` matrix and then loops in Python
over `n²/2` pairs — acceptable at a few hundred chunks, poor beyond that; use `np.triu_indices`.
Rendering is strictly sequential; clips are independent and could run in parallel. Whisper
transcription is the dominant cost and has no progress reporting.

**The entertainment agent costs a full LLM call per candidate and carries zero composite weight.**
Either give it weight or stop paying for it.

---

## 14. Product problems

**Goal:** *"A podcaster pastes one podcast URL and the AI acts like their professional video editor,
selecting the 5–10 best Shorts and producing actual publishable short videos."*

| Goal component | Status |
|---|---|
| Paste one URL | ✅ Works — text field or `--source` |
| Fully automatic | ⚠️ Partial |
| **The AI acts as editor** | ❌ **By default there is no AI** |
| Select 5–10 best | ✅ Configurable, defaults to 5–15 |
| **Produce publishable videos** | ⚠️ Produces real videos; "publishable" is a stretch |

### PP-1 — The headline claim is not true by default

This is the central product problem. Out of the box (`DEFAULT_LLM_PROVIDER=heuristic`,
`EMBEDDING_BACKEND=lexical`, no Whisper), **no AI model runs at all.** The "six AI editor agents"
are six weighted arithmetic formulas over regex-derived text features.

The repo is scrupulously honest about this — it stamps `scoring_mode`, warns in the CLI and UI, and
the README says plainly that heuristic mode is "a weak proxy for editorial judgement… not for
deciding what to publish." That honesty is admirable engineering and a **product liability**: the
default experience is explicitly labelled as not fit for the product's purpose.

A podcaster running this today gets clips chosen because they are ~45 s long, start after a pause,
end on a full stop, and contain words from a curiosity list. That is a competent *segmenter*, not
an editor.

### PP-2 — The default path cannot process most podcasts

Without `requirements-ml.txt` (~2 GB), only YouTube URLs **with existing caption tracks** work.
Local files, RSS-hosted audio, and uncaptioned videos all fail at node 3. Most podcasters'
canonical asset is an audio file, not a captioned YouTube video.

### PP-3 — Output is not publish-ready

Real 1080×1920 MP4s with captions is a genuine achievement, but against what creators actually
post:

| Expected | Present |
|---|---|
| Word-highlight captions | ❌ Static 3-word cues |
| Speaker-aware framing | ❌ Fixed centre; `crop` can decapitate |
| Punch-ins / zoom / B-roll | ❌ None |
| Branding, intro/outro | ❌ None |
| Thumbnail image | ❌ Text suggestion only |

Blur-pad 9:16 with static captions reads as automated output. It is a solid technical baseline, not
a finished short.

### PP-4 — Titles and hooks are mechanical without an LLM

Observed in a real run:

```
[#4] People forget that utility always beats novelty in the long run
     hook  : "That is incredible advice."
```

`derive_title` skips filler openers; `hook` does not — and the hook is what the viewer actually
hears in the first second. One clip received a single hashtag (`#Lasts`) because the top-up
fallback only fires on a completely empty list.

### PP-5 — No trust-building loop

There is no way to preview before rendering, adjust boundaries, regenerate one clip, or record that
a suggestion was wrong. A tool claiming editorial judgement needs a correction path.

### PP-6 — No cost transparency

Enabling LLM mode issues `shortlist_size × 6` calls (240 by default) plus one packaging call per
published clip. Nothing estimates or caps this beforehand. Combined with TP-2 (6× concurrency) and
TP-10 (retrying 401s), a first LLM run is likely to hit rate limits.

### What the product does unusually well

Provenance and honesty are genuinely differentiated. Most tools in this space present heuristic
output as AI judgement. This one refuses to, and enforces it structurally. That is worth preserving
even though it currently exposes an uncomfortable truth.

---

## 15. Competitive differentiation

### Commodity — table stakes, no advantage

- YouTube download (yt-dlp), audio extraction, Whisper transcription
- Basic 9:16 reframe with blurred padding
- Burned captions via ASS
- LLM-scored clip selection — every competitor does this
- Loudness normalisation
- A local web dashboard

Roughly 60% of the codebase is commodity infrastructure, competently built.

### Potentially differentiated

**1. Measurement-driven segmentation — the strongest asset.**
The team tested keyword splitting and lexical embedding dips, measured both against planted
boundaries, found both ineffective, and *documented the negative result in the source*. The shipped
approach uses signals that are actually reliable in speech. Most competitors either split on fixed
windows or trust an LLM to pick timestamps. A segmenter that reliably finds *self-contained* units
is the hard part of this problem and is where a real moat could exist.

**2. Provenance and refusal to fabricate.**
Every output records how it was produced; heuristic mode is a declared mode, not a hidden fallback;
every stage fails loudly. For any professional or agency user this is a genuine trust differentiator —
"we will tell you when we don't know" is rare and valuable.

**3. The multi-agent editorial panel — currently unrealised.**
Six specialised perspectives with disagreement-penalised confidence is a real idea: it can say
*"strong hook, weak story, high comment potential"* rather than a single opaque score. But today
the entertainment agent carries zero weight, the composite is a fixed linear blend, and by default
no model runs. The concept is differentiated; the implementation is not yet.

**4. Cut-point precision from measured silence.**
Adjusting boundaries into real measured pauses, with a per-clip rationale, is more principled than
fixed offsets. Wiring in the already-written `measure_silences()` would make this genuinely strong.

**5. Honest confidence scoring.**
Lowering confidence when agents disagree, and refusing to render a 0–10 score as a fake completion
percentage, is intellectually honest in a category full of invented metrics.

### Where it cannot win

Rendering sophistication. Competitors have face tracking, dynamic punch-ins, animated captions and
brand kits. Catching up is a large investment in a commodity area. The better strategy is to be
*the tool that picks the right moments* and make rendering merely good enough — or export an EDL/XML
so creators finish in their own editor.

### Sharpest strategic framing

The current output is **an editorial decision engine wearing a thin rendering layer**. The rendering
is replaceable. The segmentation and honesty are not. Investment should follow that.

---

## 16. Next steps

### P0 — must fix before any real testing

1. **Keep the checkpointer fix and add the test that would have caught it** (TP-1). One test
   constructing the real default `VideoEditorPipeline()`. This retires an entire class of bug.
2. **Reset run-scoped state per invocation** (TP-7). Clear `error`/`failed_stage` in the initial
   state, or derive a fresh thread id unless the user explicitly resumes. Today one typo
   permanently breaks the default thread id with a misleading message.
3. **Fix the audio cache key** (TP-5) and **delete the trimmer's silent media fallbacks** (TP-15).
   Both produce confident output about the wrong episode; one is fixed by deleting code.
4. **Stop labelling failed runs as fixture data** (TP-8). Add `"unavailable"` to the source literals.
5. **Add CI** — `ruff check` + `pytest` on push. Would have caught P0 on the commit that introduced it.

### P1 — build next

6. **Bound LLM concurrency with a shared semaphore** (TP-2) and **stop retrying 401/404** (TP-10).
   Do both before the next run against a paid key.
7. **Fix the apostrophe escape** (TP-3) and **the Range handler** (TP-11). Small, self-contained,
   each with an obvious test.
8. **Generate `.env.example` from `Settings`** with a test asserting they agree. Kills the
   deprecated-Gemini trap and the blank-language trap together.
9. **Fix per-word capitalisation** (TP-14) — add `sentence_case: bool` and pass `False` from the
   per-word call site. Directly visible in every rendered caption.
10. **Wire in `measure_silences()`.** Already written, already tested, zero callers. Makes the
    "measured pauses" claim true and improves cut placement.
11. **Give the entertainment agent composite weight, or remove it.** It currently costs a call per
    candidate and influences nothing.
12. **Fix the trimmer's caption path** (pass real word timings) or document that trimmer renders
    are uncaptioned.
13. **Server resource lifetime** (TP-6, TP-12, TP-13): shared pipeline instance, job TTL eviction,
    per-job index paths, thread-filtered log handler.

### P2 — experiments

14. **Word-highlight captions.** The single highest-leverage change to perceived output quality,
    and the ASS generator already has the word timings.
15. **A local sentence-transformer embedding backend** so semantic segmentation and real semantic
    dedup work offline. Directly strengthens the strongest asset.
16. **Cost estimation and a budget cap** before an LLM run.
17. **Face detection for `crop` mode** so it stops decapitating speakers.
18. **Measure whether six agents beat two or three.** Score a labelled set both ways. The panel is
    the differentiating idea and is currently unvalidated.
19. **Preview-before-render** in the UI, with adjustable boundaries.

### P3 — future

20. Real diarization (`pyannote.audio` / WhisperX) — the largest missing capability for
    multi-speaker podcasts, improving both segmentation and selection.
21. Direct publishing integrations.
22. EDL / Premiere XML / DaVinci export — plays to the strength and sidesteps the rendering arms race.
23. Batch/multi-episode queue with persistence.
24. Feedback loop from published performance.
25. Auth and multi-tenancy, if this becomes a service.
26. Storage retention policy — currently nothing is ever cleaned up.

---

## 17. On rewriting

**A rewrite is not warranted and would be a mistake.**

The architecture is the strongest part of this project. The layering is clean and consistently
respected; `analysis/` is pure and genuinely testable; `providers/` isolates every external system;
the LangGraph fan-out is correctly implemented with the reducers that make it safe; the schema layer
is thorough; the error taxonomy is well designed; the provenance system is a real asset. 532 tests
encode a lot of hard-won knowledge, including explicit regression cases for past failures.

Every P0 and P1 bug in this report is a **seam** defect — process lifetime, resource ownership,
cache keys, config drift — not a design defect. None requires structural change. The largest
single fix is one line. Most others are under twenty.

Preserve:
- The entire `src/analysis/` package — pure, tested, and the intellectual core.
- The graph structure and node decomposition in `src/nodes/` and `src/graph/`.
- The schema layer and error hierarchy.
- The provenance system, without weakening it.
- The renderer's filter graphs — they produce correct, verified output.
- The test suite, extended with the process-level tests it lacks.

Rework, do not rewrite:
- `trimmer.py` — the least mature module and the source of two data-integrity bugs. Fold its
  media resolution and clip construction into the existing renderer paths rather than maintaining
  a parallel implementation.
- `app.py` — the server logic needs resource-lifetime fixes. The embedded HTML string is
  unpleasant but works and is not the priority. If it is ever replaced, replace the transport
  (a small ASGI app), not the pipeline.

The correct next move is a focused bug-fix pass followed by CI, not a restart.

---

*Report compiled from a complete source read plus live execution. No application code was modified
in producing this report, with one exception noted throughout: the single-line checkpointer fix in
`src/graph/workflow.py` (TP-1), without which no entry point runs at all. That change is
uncommitted and visible in `git status`.*
