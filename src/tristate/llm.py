"""OpenAI-compatible structured LLM client.

Design points that matter for reproducibility:
* every request is hashed and its raw response is checkpointed BEFORE parsing;
* a content-addressed cache makes re-runs free and deterministic;
* transient errors get bounded exponential backoff with jitter, schema errors get one
  repair round, budget/credential errors fail fast;
* token usage and estimated cost are recorded per call and aggregated.
"""

from __future__ import annotations

import json
import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .config import Config, ModelCfg
from .prompts import Prompt, PromptLibrary
from .util import atomic_write_json, append_jsonl, read_json, sha256_json, utcnow

M = TypeVar("M", bound=BaseModel)

TRANSIENT_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LlmError(RuntimeError):
    """Base error for provider interactions."""


class TransientLlmError(LlmError):
    pass


class PermanentLlmError(LlmError):
    pass


class JsonParseError(PermanentLlmError):
    pass


class SchemaViolation(PermanentLlmError):
    pass


class BudgetExceeded(PermanentLlmError):
    pass


def extract_json_object(text: str) -> Any:
    """Parse the first JSON value in a model response, tolerating fences/prose."""
    if text is None:
        raise JsonParseError("empty response")
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
        s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(s):
        if ch in "{[":
            try:
                obj, _ = dec.raw_decode(s[i:])
                return obj
            except json.JSONDecodeError:
                continue
    raise JsonParseError(f"no JSON value found in response (head={s[:200]!r})")


@dataclass
class CallRecord:
    call_id: str
    run_id: str
    stage: str
    prompt_name: str
    prompt_version: str
    model: str
    request_hash: str
    status: str
    latency_ms: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    cached: bool = False
    attempt: int = 1
    family_id: str | None = None
    candidate_id: str | None = None
    error: str | None = None
    raw_ref: str | None = None
    created_at: str = field(default_factory=utcnow)

    def as_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "run_id": self.run_id,
            "stage": self.stage,
            "prompt_name": self.prompt_name,
            "prompt_version": self.prompt_version,
            "model": self.model,
            "request_hash": self.request_hash,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": round(self.cost_usd, 8),
            "cached": self.cached,
            "attempt": self.attempt,
            "family_id": self.family_id,
            "candidate_id": self.candidate_id,
            "error": self.error,
            "raw_ref": self.raw_ref,
            "created_at": self.created_at,
        }


@dataclass
class StructuredResult:
    data: BaseModel
    raw_text: str
    model: str
    prompt_version: str
    usage: dict[str, Any]
    latency_ms: int
    cached: bool
    request_hash: str
    raw_ref: str | None
    attempts: int = 1

    @property
    def prompt_tokens(self) -> int:
        return int(self.usage.get("prompt_tokens") or 0)

    @property
    def completion_tokens(self) -> int:
        return int(self.usage.get("completion_tokens") or 0)


class Transport(Protocol):
    def chat(self, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> tuple[int, dict, dict]:
        """Return (status_code, json_body, response_headers)."""


class HttpTransport:
    """Thin httpx wrapper; one client is shared across worker threads."""

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=httpx.Timeout(180.0, connect=20.0))

    def chat(self, payload, headers, timeout):
        resp = self._client.post(payload.pop("__url__"), json=payload, headers=headers, timeout=timeout)
        try:
            body = resp.json()
        except Exception:
            body = {"raw_text": resp.text}
        return resp.status_code, body, dict(resp.headers)

    def close(self) -> None:
        self._client.close()


class LlmClient:
    def __init__(
        self,
        cfg: Config,
        run_id: str,
        prompts: PromptLibrary | None = None,
        transport: Transport | None = None,
        recorder: Callable[[CallRecord], None] | None = None,
    ):
        self.cfg = cfg
        self.run_id = run_id
        self.prompts = prompts or PromptLibrary(cfg.prompts_dir)
        self.transport = transport or HttpTransport()
        self.recorder = recorder
        self.raw_dir = cfg.data_dir / "raw" / run_id
        self.cache_dir = cfg.data_dir / "llm_cache"
        self.log_path = cfg.data_dir / "logs" / "calls.jsonl"
        self._lock = threading.Lock()
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cost_usd = 0.0

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def structured(
        self,
        prompt_name: str,
        variables: dict[str, Any],
        schema: Type[M],
        model_cfg: ModelCfg,
        stage: str | None = None,
        family_id: str | None = None,
        candidate_id: str | None = None,
    ) -> StructuredResult:
        prompt = self.prompts.get(prompt_name)
        rendered = prompt.render(**variables)
        stage = stage or prompt.stage
        return self._call(
            prompt=prompt,
            rendered=rendered,
            schema=schema,
            model_cfg=model_cfg,
            stage=stage,
            family_id=family_id,
            candidate_id=candidate_id,
        )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "calls": self.calls,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "cost_usd": round(self.cost_usd, 6),
            }

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _call(
        self,
        prompt: Prompt,
        rendered: str,
        schema: Type[M],
        model_cfg: ModelCfg,
        stage: str,
        family_id: str | None,
        candidate_id: str | None,
        attempt: int = 1,
    ) -> StructuredResult:
        model = model_cfg.name
        request_hash = sha256_json(
            {
                "model": model,
                "temperature": model_cfg.temperature,
                "max_tokens": model_cfg.max_tokens,
                "prompt": prompt.full_version,
                "rendered": rendered,
                "schema": schema.__name__,
            }
        )
        cache_path = self.cache_dir / stage / f"{request_hash}.json"
        if self.cfg.llm.cache_enabled:
            cached = read_json(cache_path)
            if cached:
                try:
                    data = schema.model_validate(cached["parsed"])
                    self._record(
                        stage, prompt, model, request_hash, "CACHED",
                        latency_ms=0, usage=cached.get("usage", {}), cached=True,
                        family_id=family_id, candidate_id=candidate_id, attempt=attempt,
                    )
                    return StructuredResult(
                        data=data,
                        raw_text=cached.get("raw_text", ""),
                        model=model,
                        prompt_version=prompt.full_version,
                        usage=cached.get("usage", {}),
                        latency_ms=0,
                        cached=True,
                        request_hash=request_hash,
                        raw_ref=cached.get("raw_ref"),
                        attempts=attempt,
                    )
                except ValidationError:
                    pass  # stale/incompatible cache entry: fall through and re-call

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a precise data-generation worker. Obey the user's output "
                    "contract exactly. Return a single JSON object and no other text."
                ),
            },
            {"role": "user", "content": rendered},
        ]
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": model_cfg.temperature,
            "max_tokens": model_cfg.max_tokens,
        }
        if self.cfg.llm.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if model_cfg.extra_body:
            payload.update(model_cfg.extra_body)

        self._budget_guard()

        status, body, headers, latency_ms = self._request(payload, model_cfg)
        raw_ref = self._checkpoint(stage, request_hash, payload, status, body, headers, latency_ms)

        if status >= 400:
            err = self._provider_error(status, body)
            self._record(
                stage, prompt, model, request_hash, "ERROR", latency_ms,
                family_id=family_id, candidate_id=candidate_id, error=str(err)[:800],
                attempt=attempt, raw_ref=raw_ref,
            )
            raise err

        text, usage = self._unpack(body)
        cost = self._accumulate(usage, model_cfg)

        try:
            parsed = extract_json_object(text)
            data = schema.model_validate(parsed)
        except (JsonParseError, ValidationError) as exc:
            if attempt <= self.cfg.llm.schema_repair_attempts:
                repair_msg = (
                    "Your previous reply could not be accepted.\n"
                    f"Error: {str(exc)[:700]}\n"
                    "Return the corrected JSON object only. Keep every required field, "
                    "change only what is needed to satisfy the contract.\n"
                    f"Previous reply (truncated): {text[:2500]}"
                )
                return self._call(
                    prompt=prompt,
                    rendered=rendered + "\n\n" + repair_msg,
                    schema=schema,
                    model_cfg=model_cfg,
                    stage=stage,
                    family_id=family_id,
                    candidate_id=candidate_id,
                    attempt=attempt + 1,
                )
            self._record(
                stage, prompt, model, request_hash, "SCHEMA_ERROR", latency_ms,
                usage=usage, family_id=family_id, candidate_id=candidate_id,
                error=str(exc)[:800], attempt=attempt, raw_ref=raw_ref,
            )
            raise SchemaViolation(str(exc)) from exc

        if self.cfg.llm.cache_enabled:
            atomic_write_json(
                cache_path,
                {
                    "created_at": utcnow(),
                    "model": model,
                    "prompt_version": prompt.full_version,
                    "request_hash": request_hash,
                    "parsed": data.model_dump(mode="json"),
                    "raw_text": text,
                    "usage": usage,
                    "raw_ref": raw_ref,
                },
            )

        self._record(
            stage, prompt, model, request_hash, "OK", latency_ms, usage,
            family_id=family_id, candidate_id=candidate_id, attempt=attempt,
            raw_ref=raw_ref, cost_usd=cost,
        )
        return StructuredResult(
            data=data,
            raw_text=text,
            model=model,
            prompt_version=prompt.full_version,
            usage=usage,
            latency_ms=latency_ms,
            cached=False,
            request_hash=request_hash,
            raw_ref=raw_ref,
            attempts=attempt,
        )

    def _request(self, payload: dict[str, Any], model_cfg: ModelCfg) -> tuple[int, dict, dict, int]:
        key = self.cfg.api_key()
        if not key:
            raise PermanentLlmError(
                f"missing API key: set ${self.cfg.llm.api_key_env} (no secret is logged)"
            )
        url = self.cfg.llm.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": self.cfg.llm.user_agent,
            "Accept": "application/json",
        }
        attempts = max(1, self.cfg.execution.max_retries)
        last: LlmError | None = None
        for i in range(attempts):
            started = time.perf_counter()
            try:
                p = dict(payload)
                p["__url__"] = url
                status, body, resp_headers = self.transport.chat(
                    p, headers, self.cfg.execution.request_timeout_s
                )
            except httpx.TimeoutException:
                last = TransientLlmError(f"timeout after {self.cfg.execution.request_timeout_s}s")
                self._sleep_backoff(i)
                continue
            except httpx.HTTPError as exc:
                last = TransientLlmError(f"transport error: {exc}")
                self._sleep_backoff(i)
                continue
            elapsed = int((time.perf_counter() - started) * 1000)
            if status < 400:
                return status, body, resp_headers, elapsed
            err = self._provider_error(status, body)
            if isinstance(err, TransientLlmError) and i < attempts - 1:
                wait = self._retry_after(resp_headers)
                self._sleep_backoff(i, override=wait if wait is not None else None)
                last = err
                continue
            raise err
        raise last or TransientLlmError("provider unavailable")

    def _provider_error(self, status: int, body: dict) -> LlmError:
        detail = ""
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                detail = str(err.get("message") or err)[:500]
            elif err:
                detail = str(err)[:500]
            else:
                detail = str(body.get("raw_text") or "")[:500]
        msg = f"HTTP {status}: {detail}".strip()
        if status in TRANSIENT_STATUS:
            return TransientLlmError(msg)
        return PermanentLlmError(msg)

    def _unpack(self, body: dict) -> tuple[str, dict]:
        try:
            choice = body["choices"][0]
            msg = choice.get("message") or {}
            text = msg.get("content")
            if isinstance(text, list):  # content-part arrays
                text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
            if text is None:
                text = choice.get("text") or ""
            usage = body.get("usage") or {}
            return str(text), usage
        except (KeyError, IndexError, TypeError) as exc:
            raise PermanentLlmError(f"malformed provider response: {str(body)[:400]}") from exc

    def _retry_after(self, headers: dict) -> float | None:
        for k, v in headers.items():
            if k.lower() == "retry-after":
                try:
                    return min(float(v), self.cfg.execution.backoff_max_s)
                except (TypeError, ValueError):
                    return None
        return None

    def _sleep_backoff(self, attempt: int, override: float | None = None) -> None:
        if override is not None:
            time.sleep(max(0.0, override))
            return
        base = self.cfg.execution.backoff_base_s * (2 ** attempt)
        jitter = random.uniform(0, base * 0.4)
        time.sleep(min(base + jitter, self.cfg.execution.backoff_max_s))

    def _budget_guard(self) -> None:
        limit = self.cfg.execution.max_total_cost_usd
        if limit and limit > 0:
            with self._lock:
                if self.cost_usd >= limit:
                    raise BudgetExceeded(
                        f"budget exhausted: ${self.cost_usd:.4f} >= ${limit:.2f}"
                    )

    def _accumulate(self, usage: dict, model_cfg: ModelCfg) -> float:
        pt = int(usage.get("prompt_tokens") or 0)
        ct = int(usage.get("completion_tokens") or 0)
        cost = (pt / 1_000_000) * model_cfg.cost_in_per_mtok + (
            ct / 1_000_000
        ) * model_cfg.cost_out_per_mtok
        with self._lock:
            self.calls += 1
            self.prompt_tokens += pt
            self.completion_tokens += ct
            self.cost_usd += cost
        return cost

    def _checkpoint(
        self,
        stage: str,
        request_hash: str,
        payload: dict,
        status: int,
        body: dict,
        headers: dict,
        latency_ms: int,
    ) -> str:
        d = self.raw_dir / stage
        path = d / f"{request_hash}.json"
        safe_payload = {k: v for k, v in payload.items() if k != "__url__"}
        atomic_write_json(
            path,
            {
                "created_at": utcnow(),
                "run_id": self.run_id,
                "stage": stage,
                "request_hash": request_hash,
                "request": safe_payload,
                "status": status,
                "response": body,
                "response_headers": {
                    k: v
                    for k, v in headers.items()
                    if k.lower() in ("retry-after", "x-trace-id", "server-timing")
                },
                "latency_ms": latency_ms,
            },
        )
        return str(path)

    def _record(
        self,
        stage: str,
        prompt: Prompt,
        model: str,
        request_hash: str,
        status: str,
        latency_ms: int,
        usage: dict | None = None,
        cached: bool = False,
        family_id: str | None = None,
        candidate_id: str | None = None,
        error: str | None = None,
        attempt: int = 1,
        raw_ref: str | None = None,
        cost_usd: float = 0.0,
    ) -> CallRecord:
        usage = usage or {}
        rec = CallRecord(
            call_id=sha256_json([request_hash, status, attempt, utcnow()])[:16],
            run_id=self.run_id,
            stage=stage,
            prompt_name=prompt.name,
            prompt_version=prompt.full_version,
            model=model,
            request_hash=request_hash,
            status=status,
            latency_ms=latency_ms,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            cost_usd=cost_usd,
            cached=cached,
            attempt=attempt,
            family_id=family_id,
            candidate_id=candidate_id,
            error=error,
            raw_ref=raw_ref,
        )
        if self.recorder:
            try:
                self.recorder(rec)
            except Exception:
                pass
        try:
            append_jsonl(self.log_path, rec.as_dict())
        except OSError:
            pass
        return rec

    # ------------------------------------------------------------------ #
    def probe(self) -> dict[str, Any]:
        """Cheap credential/model probe used by `config-check`."""
        key = self.cfg.api_key()
        if not key:
            return {"ok": False, "error": f"missing ${self.cfg.llm.api_key_env}"}
        headers = {
            "Authorization": f"Bearer {key}",
            "User-Agent": self.cfg.llm.user_agent,
            "Accept": "application/json",
        }
        try:
            r = httpx.get(
                self.cfg.llm.base_url.rstrip("/") + "/models",
                headers=headers,
                timeout=30.0,
            )
            status = r.status_code
            ids: list[str] = []
            if status < 400:
                d = r.json()
                ids = [m.get("id", "") for m in d.get("data", [])]
            return {"ok": status < 400, "status": status, "model_count": len(ids),
                    "has_generator": self.cfg.llm.generator.name in ids}
        except Exception as exc:  # pragma: no cover - network dependent
            return {"ok": False, "error": str(exc)}


class MockTransport:
    """Deterministic transport for offline tests.

    ``responder`` maps a request payload to either a JSON-serialisable object (which
    is wrapped in a chat-completions envelope) or a raw response text.
    """

    def __init__(self, responder: Callable[[dict[str, Any]], Any]):
        self.responder = responder
        self.calls: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []

    def chat(self, payload, headers, timeout):
        payload = dict(payload)
        payload.pop("__url__", None)
        self.calls.append(payload)
        self.headers.append(dict(headers))
        try:
            out = self.responder(payload)
        except Exception as exc:
            return 500, {"error": {"message": str(exc)}}, {}
        if isinstance(out, tuple) and len(out) == 2:
            status, body = out
            if isinstance(body, str):
                body = {
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": body}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                }
            return int(status), body, dict(getattr(out, "__dict__", {}) or {})
        if isinstance(out, str):
            text = out
        else:
            text = json.dumps(out)
        body = {
            "id": f"mock-{len(self.calls)}",
            "object": "chat.completion",
            "model": payload.get("model", "mock"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }
        return 200, body, {}
