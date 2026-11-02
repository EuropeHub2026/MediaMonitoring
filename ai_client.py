"""Structured-output calls to the AI provider, shared by triage, coding and the brief.

One place handles the model name (from the environment), the spend-cap rule (stop, log,
record it for the page) and errors, so a failed call never produces a partial row.
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

import openai
from pydantic import BaseModel

import config

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class AIError(RuntimeError):
    """A call failed; the caller writes nothing for the affected items and retries next run."""


class SpendCapHit(AIError):
    """The provider refused for lack of quota or budget; the caller must stop."""


def record_status(cfg: dict[str, Any], service: str, state: str, detail: str = "") -> None:
    """Record a service state (e.g. a spend cap hit) in data/status.json for the method notes."""
    status_path = config.path(cfg, "status_json")
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
    status[service] = {"state": state, "detail": detail, "at": config.iso(config.now(cfg), cfg)}
    status_path.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")


def make_client() -> openai.OpenAI:
    """Return an OpenAI client using OPENAI_API_KEY from the environment."""
    return openai.OpenAI(api_key=config.get_secret("OPENAI_API_KEY"), max_retries=2)


def log_usage(model: str, response: Any) -> None:
    """Log the tokens one response used, so real costs can be read from the logs."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    cached = getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0)
    reasoning = getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0)
    log.info("usage model=%s input=%s cached=%s output=%s reasoning=%s",
             model, usage.input_tokens, cached, usage.output_tokens, reasoning)


def parse_structured(
    cfg: dict[str, Any],
    client: Any,
    model_env: str,
    instructions: str,
    user_input: str,
    schema: type[T],
) -> tuple[T, str]:
    """Ask the model for output matching `schema`; return (parsed object, model name).

    Raises SpendCapHit on quota or budget errors (after recording it) and AIError on any
    other failure, including output that does not validate.
    """
    model = config.get_secret(model_env)
    kwargs: dict[str, Any] = {}
    if cfg.get("coding", {}).get("temperature") is not None:
        kwargs["temperature"] = cfg["coding"]["temperature"]
    try:
        response = client.responses.parse(
            model=model, instructions=instructions, input=user_input, text_format=schema, **kwargs
        )
    except openai.RateLimitError as exc:
        if "insufficient_quota" in str(exc) or "billing" in str(exc).lower():
            log.error("AI spend cap reached: %s", exc)
            record_status(cfg, "openai", "cap_hit", "AI provider quota or budget reached; coding stopped.")
            raise SpendCapHit(str(exc)) from exc
        raise AIError(f"rate limited: {exc}") from exc
    except openai.OpenAIError as exc:
        raise AIError(str(exc)) from exc
    except ValueError as exc:   # pydantic validation of the model's output
        raise AIError(f"output did not validate: {exc}") from exc
    log_usage(model, response)
    parsed = getattr(response, "output_parsed", None)
    if parsed is None:
        raise AIError("no parsed output (refusal or empty response)")
    return parsed, model
