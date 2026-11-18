"""One LLM client for every stage: many providers, schema-validated JSON, quota-aware fallback.

Model specs are `provider:model`, e.g. `groq:openai/gpt-oss-120b`, `ollama:qwen3:8b`,
`openrouter:qwen/qwen3-235b-a22b`, `cerebras:gpt-oss-120b`, `gemini:gemma-3-27b-it`. A bare
model id uses ANCHOR_BASE_URL/ANCHOR_API_KEY. Each role (writer, critic, improver, selector)
gets its own chain: primary first, then ANCHOR_FALLBACK_MODELS; providers without a key are
skipped. A daily-quota 429 trips a circuit breaker so later calls skip that model at once.

Every structured call is validated against a pydantic schema and the exact validation error is
fed back for repair. A call that cannot be satisfied RAISES; nothing downstream invents defaults.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .config import Settings, settings

log = logging.getLogger("anchor.llm")
T = TypeVar("T", bound=BaseModel)

_RETRY_HINT = re.compile(r"try again in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", re.I)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)
_THINK = re.compile(r"<think>.*?</think>", re.S)
_DAILY = re.compile(r"(tokens|requests) per day|\bTPD\b|\bRPD\b|daily", re.I)

# provider -> (base url, env vars holding the key). "ollama" uses its native API (see _ollama).
PROVIDERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "groq": ("https://api.groq.com/openai/v1", ("GROQ_API_KEY", "GROQ_KEY")),
    "openrouter": ("https://openrouter.ai/api/v1", ("OPENROUTER_API_KEY",)),
    "cerebras": ("https://api.cerebras.ai/v1", ("CEREBRAS_API_KEY",)),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
    "together": ("https://api.together.xyz/v1", ("TOGETHER_API_KEY",)),
    "ollama": (os.environ.get("OLLAMA_HOST", "http://localhost:11434"), ()),
}

_tripped: dict[str, float] = {}  # spec -> unix time until which it is skipped
_usage: dict[str, list[int]] = {}  # spec -> [calls, prompt tokens, completion tokens]
_usage_lock = threading.Lock()


def record_usage(spec: str, prompt: int, completion: int) -> None:
    with _usage_lock:
        row = _usage.setdefault(spec, [0, 0, 0])
        row[0] += 1
        row[1] += int(prompt or 0)
        row[2] += int(completion or 0)


def usage_snapshot() -> dict[str, dict[str, int]]:
    """Tokens used per model since process start (or the last reset), for cost reporting."""
    with _usage_lock:
        return {k: {"calls": v[0], "prompt_tokens": v[1], "completion_tokens": v[2]} for k, v in _usage.items()}


def reset_usage() -> None:
    with _usage_lock:
        _usage.clear()
_trip_lock = threading.Lock()


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class Endpoint:
    spec: str
    provider: str
    model: str
    base_url: str
    api_key: str


def resolve(spec: str, cfg: Settings) -> Endpoint | None:
    """`provider:model` -> Endpoint, or None when that provider has no credentials."""
    prefix, _, rest = spec.partition(":")
    if prefix in PROVIDERS and rest:
        base, keys = PROVIDERS[prefix]
        key = next((os.environ[k] for k in keys if os.environ.get(k)), "")
        if keys and not key:
            return None
        if prefix == "ollama":
            base = os.environ.get("OLLAMA_HOST", base)
            if not base.startswith("http"):
                base = "http://" + base
        return Endpoint(spec, prefix, rest, base, key)
    if not cfg.api_key:
        return None
    return Endpoint(spec, "custom", spec, cfg.base_url, cfg.api_key)


def _trip(spec: str, seconds: float, why: str) -> None:
    with _trip_lock:
        _tripped[spec] = time.time() + seconds
    log.warning("Model %s unavailable for ~%.0f min (%s); using fallbacks", spec, seconds / 60, why)


def _is_tripped(spec: str) -> bool:
    with _trip_lock:
        return _tripped.get(spec, 0) > time.time()


class LLM:
    def __init__(self, model: str, *, cfg: Settings | None = None, max_tokens: int | None = None):
        self.cfg = cfg or settings()
        self.model = model
        self.max_tokens = max_tokens or self.cfg.max_tokens
        chain = [m.strip() for m in model.split(",") if m.strip()]  # a role may list its own chain
        specs = chain + [m for m in self.cfg.fallback_models if m not in chain]
        self.endpoints = [e for e in (resolve(s, self.cfg) for s in specs) if e]
        self._lock = threading.Lock()
        self.calls = 0

    # -- transport ---------------------------------------------------------------------

    def _post(self, ep: Endpoint, messages: list[dict], temperature: float, json_mode: bool) -> str:
        if ep.provider == "ollama":
            return self._ollama(ep, messages, temperature, json_mode)
        body: dict = {"model": ep.model, "messages": messages, "temperature": temperature,
                      "max_tokens": self.max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if ep.provider in ("groq", "cerebras", "custom") and "gpt-oss" in ep.model and self.cfg.reasoning_effort:
            body["reasoning_effort"] = self.cfg.reasoning_effort  # hidden reasoning is billed output
        elif ep.provider in ("groq", "cerebras") and "qwen" in ep.model and self.cfg.qwen_reasoning:
            body["reasoning_effort"] = self.cfg.qwen_reasoning
        resp = httpx.post(f"{ep.base_url.rstrip('/')}/chat/completions",
                          headers={"Authorization": f"Bearer {ep.api_key}"}, json=body, timeout=240)
        if resp.status_code == 400 and json_mode and "response_format" in resp.text:
            body.pop("response_format")  # provider/model lacks JSON mode; the parser copes
            resp = httpx.post(f"{ep.base_url.rstrip('/')}/chat/completions",
                              headers={"Authorization": f"Bearer {ep.api_key}"}, json=body, timeout=240)
        if resp.status_code == 200:
            data = resp.json()
            usage = data.get("usage") or {}
            record_usage(ep.spec, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
            choice = data["choices"][0]
            content = choice["message"].get("content") or ""
            if not content.strip() and choice.get("finish_reason") == "length":
                # Hidden reasoning consumed the whole budget: repeating the same request would
                # bill the same tokens for the same empty answer, so move to the next model.
                raise _HTTPError(499, "reply truncated before any content (reasoning used max_tokens)", None)
            return content
        raise _HTTPError(resp.status_code, resp.text[:600], _retry_after(resp))

    def _ollama(self, ep: Endpoint, messages: list[dict], temperature: float, json_mode: bool) -> str:
        """Native API: the OpenAI-compatible one ignores num_ctx and silently truncates long
        prompts at the server default (a few thousand tokens), which breaks Harness² missions."""
        prompt_chars = sum(len(m["content"]) for m in messages)
        need = int(prompt_chars / 3.2) + self.max_tokens + 1024
        num_ctx = min(self.cfg.ollama_max_ctx, max(8192, -(-need // 4096) * 4096))
        if need > self.cfg.ollama_max_ctx:
            raise _HTTPError(413, f"prompt needs ~{need} tokens > ANCHOR_OLLAMA_MAX_CTX={self.cfg.ollama_max_ctx}", None)
        body = {"model": ep.model, "messages": messages, "stream": False,
                "options": {"temperature": temperature, "num_ctx": num_ctx, "num_predict": self.max_tokens}}
        if json_mode:
            body["format"] = "json"
        if not self.cfg.ollama_think:
            body["think"] = False  # qwen3/deepseek-r1 style reasoning is very slow on CPU
        resp = httpx.post(f"{ep.base_url.rstrip('/')}/api/chat", json=body, timeout=self.cfg.ollama_timeout)
        if resp.status_code == 200:
            data = resp.json()
            record_usage(ep.spec, data.get("prompt_eval_count", 0), data.get("eval_count", 0))
            return data.get("message", {}).get("content") or ""
        raise _HTTPError(resp.status_code, resp.text[:600], None)

    def complete(self, system: str, user: str, *, temperature: float = 0.4, json_mode: bool = False,
                 history: list[dict] | None = None) -> str:
        if not self.endpoints:
            raise LLMError(f"No usable endpoint for {self.model!r}: add the provider's API key to .env, "
                           "or set a model on a configured provider (see README, Models and endpoints)")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        messages += history or []
        last = ""
        for ep in self.endpoints:
            if _is_tripped(ep.spec):
                last = f"{ep.spec}: skipped (quota exhausted earlier in this process)"
                continue
            for attempt in range(6):
                try:
                    text = self._post(ep, messages, temperature, json_mode)
                    with self._lock:
                        self.calls += 1
                    return _THINK.sub("", text).strip()
                except _HTTPError as exc:
                    last = f"{ep.spec}: HTTP {exc.status}: {exc.body[:220]}"
                    if exc.status == 400 and "json_validate_failed" in exc.body and json_mode:
                        return _failed_generation(exc.body)  # caller's repair loop handles it
                    if exc.status == 429 and (_DAILY.search(exc.body) or (exc.retry_after or 0) > 120):
                        _trip(ep.spec, exc.retry_after or 3600, "daily quota" if _DAILY.search(exc.body) else "long wait")
                        break
                    if exc.status in (429, 500, 502, 503, 504) or exc.status >= 520:
                        wait = exc.retry_after or min(2 ** attempt * 2.0, 30.0)
                        log.info("LLM %s busy (HTTP %s); retrying in %.1fs", ep.spec, exc.status, wait)
                        time.sleep(wait)
                        continue
                    if exc.status in (401, 403, 404, 413, 499):
                        break  # bad key / unknown model / request too large here: try the next endpoint
                    raise LLMError(last) from None
                except httpx.HTTPError as exc:
                    last = f"{ep.spec}: {type(exc).__name__}: {exc}"
                    time.sleep(min(2 ** attempt, 20))
            log.warning("Endpoint %s gave up (%s); trying next fallback", ep.spec, last[:200])
        raise LLMError(f"All endpoints failed for {self.model!r}. Last error: {last}")

    def token_limit(self) -> int | None:
        """Per-minute token limit the primary endpoint reports (x-ratelimit-limit-tokens), probed
        with a 1-token request. None when the endpoint reports none (local servers)."""
        ep = self.endpoints[0] if self.endpoints else None
        if ep is None or ep.provider == "ollama":
            return None
        try:
            resp = httpx.post(f"{ep.base_url.rstrip('/')}/chat/completions",
                              headers={"Authorization": f"Bearer {ep.api_key}"},
                              json={"model": ep.model, "messages": [{"role": "user", "content": "ok"}],
                                    "max_tokens": 1}, timeout=30)
            if resp.status_code == 429 and _DAILY.search(resp.text):
                return 0  # daily quota already spent
            value = resp.headers.get("x-ratelimit-limit-tokens") or resp.headers.get("x-ratelimit-limit-tokens-minute")
            return int(value) if value and value.isdigit() else None
        except httpx.HTTPError:
            return None

    # -- structured --------------------------------------------------------------------

    def json(self, system: str, user: str, schema: type[T], *, temperature: float = 0.3,
             repairs: int = 2) -> T:
        """Return a validated `schema` instance or raise LLMError. Never returns defaults."""
        shape = json.dumps(_schema_hint(schema), indent=1)
        user_full = (
            f"{user}\n\nRespond with ONE JSON object only (no prose, no markdown) matching:\n{shape}"
        )
        history: list[dict] = []
        error = ""
        for _ in range(repairs + 1):
            raw = self.complete(system, user_full, temperature=temperature, json_mode=True, history=history)
            try:
                return schema.model_validate(_parse_json(raw))
            except (ValueError, ValidationError) as exc:
                error = _short_error(exc)
                log.info("Schema repair needed for %s: %s", schema.__name__, error[:200])
                history = [
                    {"role": "assistant", "content": raw[:6000] or "(empty)"},
                    {"role": "user", "content": f"That response was invalid: {error}\n"
                     "Return the corrected JSON object only."},
                ]
        raise LLMError(f"{schema.__name__}: could not obtain valid JSON ({error})")


class _HTTPError(Exception):
    def __init__(self, status: int, body: str, retry_after: float | None):
        self.status, self.body, self.retry_after = status, body, retry_after


def _retry_after(resp: httpx.Response) -> float | None:
    header = resp.headers.get("retry-after")
    if header:
        try:
            return float(header) + 0.5
        except ValueError:
            pass
    m = _RETRY_HINT.search(resp.text)
    if m:
        return float(m.group(1) or 0) * 3600 + float(m.group(2) or 0) * 60 + float(m.group(3)) + 0.5
    return None


def _failed_generation(body: str) -> str:
    try:
        return json.loads(body)["error"].get("failed_generation", "") or ""
    except Exception:
        return ""


def _parse_json(raw: str) -> dict:
    text = _FENCE.sub("", _THINK.sub("", raw or "").strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON object found in the response")
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("top-level JSON must be an object")
    return data


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'root'}: {e['msg']}" for e in exc.errors()[:8]
        )
    return str(exc)[:300]


def _schema_hint(schema: type[BaseModel]) -> dict:
    """A compact, model-readable shape: field -> description/type, nested models expanded."""

    def walk(model: type[BaseModel]) -> dict:
        out = {}
        for name, f in model.model_fields.items():
            ann = f.annotation
            inner = getattr(ann, "__args__", None)
            target = inner[0] if inner else ann
            is_list = getattr(ann, "__origin__", None) is list
            if isinstance(target, type) and issubclass(target, BaseModel):
                out[name] = [walk(target)] if is_list else walk(target)
            elif is_list:
                out[name] = [f.description or "string"]
            else:
                out[name] = f.description or getattr(ann, "__name__", str(ann))
        return out

    return walk(schema)
