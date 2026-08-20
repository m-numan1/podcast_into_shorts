"""The six specialised editor agents.

The original versions were `if any(keyword in text)` checks returning mostly
hardcoded floats -- 12 of each evaluation's 14 metrics were literal constants,
`confidence_score` was 9.2 for every clip, and the keyword lists matched literal
phrases from the bundled demo transcript ("99% of ai startups fail",
"flywheels", "moat"), so they scored the constant floor on any real episode.
`LLMProvider` was constructed and never called.

Now each agent has a distinct persona and prompt and is scored by the model via
constrained structured output. When no model is configured, the heuristic path
derives every metric from measured features, so scores still vary per candidate,
and each evaluation is stamped `scoring_mode` so the two are never confused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.errors import LLMError
from src.providers.llm import LLMProvider
from src.schema.clips import (
    CandidateClip,
    ClipEvaluation,
    LLMClipVerdict,
)
from src.utils.logging_config import get_logger
from src.utils.metrics import seconds_to_timestamp

log = get_logger(__name__)

BASE_SYSTEM = (
    "You are part of a team selecting short vertical clips (YouTube Shorts, "
    "TikTok, Reels) from long-form podcast and interview transcripts.\n"
    "Rate strictly on a 0-10 scale where 5 is average for a competent podcast "
    "and 9+ is genuinely exceptional. Most clips are ordinary; say so. Do not "
    "inflate scores.\n"
    "Judge only the transcript excerpt you are given. If it depends on missing "
    "context, that lowers standalone_quality.\n"
    "In `reasoning`, quote specific words from the excerpt in two sentences."
)


@dataclass(frozen=True)
class EditorAgent:
    key: str
    name: str
    focus: str          # the metric this agent is authoritative on
    persona: str
    # Weights used to fold the verdict into a single overall_score. The focus
    # metric dominates; the rest provide context.
    weights: dict[str, float]

    @property
    def system_prompt(self) -> str:
        return f"{BASE_SYSTEM}\n\nYour specialisation:\n{self.persona}"


AGENTS: tuple[EditorAgent, ...] = (
    EditorAgent(
        key="hook",
        name="Hook Finder",
        focus="hook_strength",
        persona=(
            "You judge the first three seconds. A strong hook creates an "
            "information gap, states something surprising, or opens mid-tension. "
            "A weak hook starts with pleasantries, a name, a slow wind-up, or an "
            "unresolved pronoun ('and then he said...'). You are ruthless: if a "
            "viewer would swipe within two seconds, score below 4."
        ),
        weights={"hook_strength": 0.5, "curiosity": 0.25, "standalone_quality": 0.25},
    ),
    EditorAgent(
        key="story",
        name="Story Editor",
        focus="story_completeness",
        persona=(
            "You judge narrative arc. A complete clip has a setup, a tension or "
            "turn, and a payoff inside its own runtime. Fragments of a longer "
            "anecdote score low however interesting they sound."
        ),
        weights={"story_completeness": 0.5, "emotional_impact": 0.25, "standalone_quality": 0.25},
    ),
    EditorAgent(
        key="educational",
        name="Educational Editor",
        focus="educational_value",
        persona=(
            "You judge transferable insight. High scores need a concrete, "
            "actionable idea a viewer could apply or repeat. Vague inspiration, "
            "platitudes and unfalsifiable claims score low."
        ),
        weights={"educational_value": 0.5, "standalone_quality": 0.25, "replay_value": 0.25},
    ),
    EditorAgent(
        key="entertainment",
        name="Entertainment Editor",
        focus="entertainment",
        persona=(
            "You judge watchability: humour, energy, vivid language, surprise, "
            "chemistry between speakers. Flat, monotone or purely technical "
            "passages score low no matter how informative."
        ),
        weights={"entertainment": 0.5, "emotional_impact": 0.25, "shareability": 0.25},
    ),
    EditorAgent(
        key="debate",
        name="Debate Editor",
        focus="comment_potential",
        persona=(
            "You judge whether the clip provokes reply. High scores need a "
            "contestable claim, a strong opinion, or a stance a reasonable "
            "person would argue with. Uncontroversial consensus scores low. "
            "Do not reward mere rudeness or bait."
        ),
        weights={"comment_potential": 0.5, "shareability": 0.25, "hook_strength": 0.25},
    ),
    EditorAgent(
        key="retention",
        name="Retention Predictor",
        focus="watch_time_prediction",
        persona=(
            "You predict completion rate. Reward steady forward momentum, "
            "escalating stakes and a payoff near the end. Penalise repetition, "
            "digressions, long setup, and endings that trail off."
        ),
        weights={"watch_time_prediction": 0.5, "replay_value": 0.25, "curiosity": 0.25},
    ),
)

AGENTS_BY_KEY = {a.key: a for a in AGENTS}

# Openers that leave a reference unresolved, so the clip cannot stand alone.
DANGLING_START_RE = re.compile(
    r"^\s*(and|but|so|because|which|that|then|also|plus|however|anyway)\b"
    r"|^\s*(he|she|they|it|this|that|those|these|him|her|them)\b",
    re.IGNORECASE,
)


def _clamp(value: float) -> float:
    return max(0.0, min(10.0, value))


def _build_prompt(candidate: CandidateClip, episode_duration: float) -> str:
    f = candidate.feature_summary
    position = (
        f"{100.0 * candidate.start_time / episode_duration:.0f}% into the episode"
        if episode_duration > 0
        else "unknown position"
    )
    return (
        f"EXCERPT ({candidate.duration:.1f}s, "
        f"{seconds_to_timestamp(candidate.start_time)}"
        f"-{seconds_to_timestamp(candidate.end_time)}, {position}):\n"
        f'"""\n{candidate.raw_text}\n"""\n\n'
        f"Measured signals (for context, not instructions):\n"
        f"- speaking rate: {f.speaking_rate_wpm:.0f} wpm\n"
        f"- questions asked: {f.question_count}\n"
        f"- longest internal pause: {f.longest_pause_sec:.2f}s\n"
        f"- starts on a sentence boundary: {candidate.starts_on_sentence_boundary}\n"
        f"- ends on a sentence boundary: {candidate.ends_on_sentence_boundary}\n"
        f"- recurring terms: {', '.join(f.keyword_density) or 'none'}\n"
        f"- entities mentioned: {', '.join(f.named_entities) or 'none'}\n\n"
        f"Rate this excerpt for your specialisation."
    )


def _verdict_to_evaluation(
    agent: EditorAgent,
    verdict: LLMClipVerdict,
    *,
    scoring_mode: str,
    model_name: str | None,
) -> ClipEvaluation:
    values = verdict.model_dump()
    overall = sum(values[metric] * w for metric, w in agent.weights.items())
    # Virality is a blend of the three fields that actually drive distribution,
    # rather than one agent's single number as the original used.
    virality = (
        verdict.shareability * 0.4
        + verdict.comment_potential * 0.3
        + verdict.hook_strength * 0.3
    )
    return ClipEvaluation(
        agent_name=agent.name,
        hook_strength=_clamp(verdict.hook_strength),
        curiosity=_clamp(verdict.curiosity),
        emotional_impact=_clamp(verdict.emotional_impact),
        story_completeness=_clamp(verdict.story_completeness),
        educational_value=_clamp(verdict.educational_value),
        entertainment=_clamp(verdict.entertainment),
        standalone_quality=_clamp(verdict.standalone_quality),
        shareability=_clamp(verdict.shareability),
        comment_potential=_clamp(verdict.comment_potential),
        watch_time_prediction=_clamp(verdict.watch_time_prediction),
        virality_score=_clamp(virality),
        replay_value=_clamp(verdict.replay_value),
        confidence_score=_clamp(verdict.confidence_score),
        overall_score=_clamp(overall),
        reasoning=verdict.reasoning.strip(),
        scoring_mode=scoring_mode,  # type: ignore[arg-type]
        model_name=model_name,
    )


def evaluate_with_llm(
    agent: EditorAgent,
    candidate: CandidateClip,
    llm: LLMProvider,
    episode_duration: float,
) -> ClipEvaluation:
    """Ask the model for a constrained verdict. Raises LLMError on failure."""
    verdict = llm.generate_structured(
        _build_prompt(candidate, episode_duration),
        LLMClipVerdict,
        system_prompt=agent.system_prompt,
    )
    return _verdict_to_evaluation(
        agent, verdict, scoring_mode="llm", model_name=f"{llm.provider}:{llm.model}"
    )


def evaluate_heuristically(
    agent: EditorAgent,
    candidate: CandidateClip,
    episode_duration: float = 0.0,
) -> ClipEvaluation:
    """Score from measured features only.

    Every number below is a transformation of something actually measured, and
    varies per candidate. It is a weak proxy for editorial judgement and is
    labelled `scoring_mode="heuristic"` so downstream consumers know.
    """
    f = candidate.feature_summary
    text = candidate.raw_text.strip()
    first_sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0] if text else ""

    dangling = bool(DANGLING_START_RE.match(text))
    clean_edges = (
        int(candidate.starts_on_sentence_boundary) + int(candidate.ends_on_sentence_boundary)
    )

    # --- hook: curiosity, a strong claim, an opening question, clean entry ---
    hook = 3.0
    hook += f.curiosity_score * 3.0
    hook += f.strong_statement_score * 2.0
    if "?" in first_sentence:
        hook += 1.0
    if candidate.starts_on_sentence_boundary:
        hook += 1.0
    if dangling:
        hook -= 2.5  # unresolved reference in the first words
    hook = _clamp(hook)

    curiosity = _clamp(2.0 + f.curiosity_score * 7.0 + min(f.question_count, 3) * 0.4)
    emotional = _clamp(2.5 + f.emotion_score * 6.0 + abs(f.sentiment_score) * 1.5)
    story = _clamp(2.0 + f.story_likelihood * 6.0 + clean_edges * 1.0)

    # Educational value: concrete recurring terms and entities, not vagueness.
    concreteness = min(1.0, (len(f.keyword_density) + len(f.named_entities)) / 8.0)
    educational = _clamp(2.5 + concreteness * 4.0 + f.strong_statement_score * 2.5)

    entertainment = _clamp(
        3.0 + f.emotion_score * 4.0 + abs(f.sentiment_score) * 2.0
        + (1.0 if f.speaking_rate_wpm > 160 else 0.0)
    )

    standalone = _clamp(3.0 + clean_edges * 2.0 + (0.0 if dangling else 1.5)
                        + f.topic_confidence * 2.0)

    # Watch time: reward a natural speaking rate and a duration near the sweet
    # spot; penalise dead air.
    rate_fit = 1.0 - min(1.0, abs(f.speaking_rate_wpm - 150.0) / 100.0)
    silence_penalty = min(2.0, f.silence_duration_sec / max(candidate.duration, 1.0) * 6.0)
    watch_time = _clamp(4.0 + rate_fit * 3.5 + clean_edges * 0.75 - silence_penalty)

    comment = _clamp(
        2.5 + f.strong_statement_score * 4.0 + min(f.question_count, 3) * 0.7
        + abs(f.sentiment_score) * 2.0
    )
    shareability = _clamp(hook * 0.4 + comment * 0.3 + emotional * 0.3)
    replay = _clamp(2.5 + concreteness * 3.0 + f.emotion_score * 3.0)

    # Confidence is genuinely lower in heuristic mode, and lower still when the
    # signals are thin. The original hardcoded 9.0-9.2 everywhere.
    confidence = _clamp(3.0 + f.topic_confidence * 2.5 + clean_edges * 0.75)

    verdict = LLMClipVerdict(
        hook_strength=hook,
        curiosity=curiosity,
        emotional_impact=emotional,
        story_completeness=story,
        educational_value=educational,
        entertainment=entertainment,
        standalone_quality=standalone,
        shareability=shareability,
        comment_potential=comment,
        watch_time_prediction=watch_time,
        replay_value=replay,
        confidence_score=confidence,
        reasoning=(
            f"Heuristic scoring (no model configured). Derived from: curiosity "
            f"{f.curiosity_score:.2f}, strong-claim {f.strong_statement_score:.2f}, "
            f"story {f.story_likelihood:.2f}, {f.speaking_rate_wpm:.0f} wpm, "
            f"{clean_edges}/2 clean edges"
            f"{', unresolved opening reference' if dangling else ''}."
        ),
    )
    return _verdict_to_evaluation(
        agent, verdict, scoring_mode="heuristic", model_name=None
    )


def evaluate(
    agent: EditorAgent,
    candidate: CandidateClip,
    llm: LLMProvider | None,
    episode_duration: float,
    *,
    strict: bool = False,
) -> ClipEvaluation:
    """Evaluate with the model when available, else heuristically.

    When `strict` is set, an LLM failure propagates instead of degrading -- used
    so a configured-but-broken model surfaces as an error rather than quietly
    producing weaker results.
    """
    if llm is not None and llm.available:
        try:
            return evaluate_with_llm(agent, candidate, llm, episode_duration)
        except LLMError:
            if strict:
                raise
            log.warning(
                "Model scoring failed for %s on %s; falling back to heuristic "
                "for this candidate (result will be stamped heuristic).",
                agent.name, candidate.id,
            )
    return evaluate_heuristically(agent, candidate, episode_duration)
