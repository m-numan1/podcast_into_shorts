"""LLM access with structured output, retries and an on-disk response cache.

The original `_structured_fallback` returned a fixed JSON blob claiming
`overall_score: 8.8` and "High-impact narrative shift with strong curiosity
hook" -- regardless of the prompt, and silently, whenever a key was missing or a
call failed. Any consumer treating that as a model judgement was being misled,
so it is gone. Failures raise `LLMError`.

Scoring without a model is still supported, but as an explicitly selected mode
(`DEFAULT_LLM_PROVIDER=heuristic`) that stamps `scoring_mode="heuristic"` onto
every result -- not as a hidden fallback.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from config.settings import settings
from src.errors import LLMError, MissingDependencyError
from src.utils.logging_config import get_logger

log = get_logger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)

_cache_lock = threading.Lock()
_client_lock = threading.Lock()
_client_cache: dict[tuple[str, str, float], object] = {}


def _cache_dir() -> Path:
    d = settings.cache_dir / "llm_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:32]


class LLMProvider:
    """Wraps whichever chat model is configured."""

    def __init__(self, provider: str | None = None, model: str | None = None):
        self.provider = provider or settings.default_llm_provider
        if model:
            self.model = model
        elif self.provider == "gemini":
            self.model = settings.gemini_model
        else:
            self.model = settings.default_model

    @property
    def available(self) -> bool:
        """True when a real model can be called."""
        if self.provider == "openai":
            return bool(settings.openai_api_key)
        if self.provider == "gemini":
            return bool(settings.gemini_api_key)
        return False

    # ------------------------------------------------------------- clients

    def _build_client(self):
        key = (self.provider, self.model, settings.llm_temperature)
        with _client_lock:
            if key in _client_cache:
                return _client_cache[key]

            if self.provider == "openai":
                try:
                    from langchain_openai import ChatOpenAI
                except ImportError as exc:
                    raise MissingDependencyError(
                        "langchain-openai", "pip install langchain-openai"
                    ) from exc
                if not settings.openai_api_key:
                    raise LLMError(
                        "OPENAI_API_KEY is not set.",
                        "Set the key, or use DEFAULT_LLM_PROVIDER=heuristic.",
                    )
                client = ChatOpenAI(
                    model=self.model,
                    api_key=settings.openai_api_key,
                    temperature=settings.llm_temperature,
                    timeout=settings.llm_timeout_sec,
                    max_retries=0,  # we handle retries ourselves
                )
            elif self.provider == "gemini":
                try:
                    from langchain_google_genai import ChatGoogleGenerativeAI
                except ImportError as exc:
                    raise MissingDependencyError(
                        "langchain-google-genai", "pip install langchain-google-genai"
                    ) from exc
                if not settings.gemini_api_key:
                    raise LLMError(
                        "GEMINI_API_KEY is not set.",
                        "Set the key, or use DEFAULT_LLM_PROVIDER=heuristic.",
                    )
                client = ChatGoogleGenerativeAI(
                    # Honours the configured model instead of hardcoding
                    # gemini-1.5-flash as the original did.
                    model=self.model,
                    google_api_key=settings.gemini_api_key,
                    temperature=settings.llm_temperature,
                    timeout=settings.llm_timeout_sec,
                    max_retries=0,
                )
            else:
                raise LLMError(
                    f"Provider {self.provider!r} cannot make model calls.",
                    "Use DEFAULT_LLM_PROVIDER=openai or =gemini.",
                )

            _client_cache[key] = client
            return client

    # -------------------------------------------------------------- calls

    def _retry(self, fn, what: str):
        """Run `fn` with exponential backoff, then raise LLMError."""
        last: Exception | None = None
        for attempt in range(settings.llm_max_retries + 1):
            try:
                return fn()
            except Exception as exc:
                last = exc
                if attempt < settings.llm_max_retries:
                    delay = min(2.0**attempt, 30.0)
                    log.warning(
                        "%s attempt %d/%d failed (%s: %s); retrying in %.0fs",
                        what, attempt + 1, settings.llm_max_retries + 1,
                        type(exc).__name__, exc, delay,
                    )
                    time.sleep(delay)
        raise LLMError(
            f"{what} failed after {settings.llm_max_retries + 1} attempts: "
            f"{type(last).__name__}: {last}",
            "Check the API key, quota and network connectivity.",
        ) from last

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        """Free-text completion. Raises LLMError on failure."""
        cache_id = _cache_key("text", self.provider, self.model, system_prompt or "", prompt)
        cached = self._read_cache(cache_id)
        if cached is not None:
            return cached["text"]

        client = self._build_client()
        messages: list[tuple[str, str]] = []
        if system_prompt:
            messages.append(("system", system_prompt))
        messages.append(("human", prompt))

        result = self._retry(
            lambda: client.invoke(messages), f"{self.provider}:{self.model} generate"
        )
        text = str(getattr(result, "content", result))
        self._write_cache(cache_id, {"text": text})
        return text

    def generate_structured(
        self,
        prompt: str,
        schema: type[TModel],
        system_prompt: str | None = None,
    ) -> TModel:
        """Completion validated against `schema`. Raises LLMError on failure.

        Uses the provider's native structured-output mode so the model is
        constrained to the schema instead of being asked to emit JSON and hoped
        at.
        """
        cache_id = _cache_key(
            "struct", self.provider, self.model, schema.__name__,
            json.dumps(schema.model_json_schema(), sort_keys=True),
            system_prompt or "", prompt,
        )
        cached = self._read_cache(cache_id)
        if cached is not None:
            try:
                return schema.model_validate(cached)
            except Exception:
                log.debug("Discarding stale cache entry for %s", cache_id)

        client = self._build_client()
        try:
            structured = client.with_structured_output(schema)
        except AttributeError as exc:
            raise LLMError(
                f"{self.provider} client does not support structured output.",
                "Upgrade langchain-openai / langchain-google-genai.",
            ) from exc

        messages: list[tuple[str, str]] = []
        if system_prompt:
            messages.append(("system", system_prompt))
        messages.append(("human", prompt))

        result = self._retry(
            lambda: structured.invoke(messages),
            f"{self.provider}:{self.model} structured({schema.__name__})",
        )
        if result is None:
            raise LLMError(
                f"{self.provider} returned no parseable {schema.__name__}.",
                "The model may have refused or emitted malformed output.",
            )
        if not isinstance(result, schema):
            result = schema.model_validate(result)
        self._write_cache(cache_id, result.model_dump(mode="json"))
        return result

    # -------------------------------------------------------------- cache

    @staticmethod
    def _read_cache(cache_id: str) -> dict | None:
        if not settings.llm_cache_enabled:
            return None
        path = _cache_dir() / f"{cache_id}.json"
        if not path.exists():
            return None
        try:
            with _cache_lock:
                data = json.loads(path.read_text(encoding="utf-8"))
            log.debug("LLM cache hit %s", cache_id)
            return data
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _write_cache(cache_id: str, payload: dict) -> None:
        if not settings.llm_cache_enabled:
            return
        path = _cache_dir() / f"{cache_id}.json"
        tmp = path.with_suffix(".json.tmp")
        try:
            with _cache_lock:
                tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                tmp.replace(path)
        except OSError as exc:
            log.debug("Could not write LLM cache: %s", exc)
