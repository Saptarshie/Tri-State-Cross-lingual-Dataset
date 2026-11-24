"""Two-axis style: tone (register) and narrative (mode/stance).

Tone is sampled from the configured register list; narrative is sampled from the
mode list. Both are fixed per family so the three variants cannot be separated by
surface style. A small YAML library supplies a directive and one short exemplar per
axis, plus composed exemplars for known conflict pairs. Exemplars teach style only;
prompts forbid reusing their topics, names or wording.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .config import Config

DEFAULT_TONE_DIRECTIVE = (
    "Write in the requested register consistently. Keep sentence rhythm and vocabulary "
    "within that register for the whole section."
)
DEFAULT_NARRATIVE_DIRECTIVE = (
    "Use the requested narrative mode consistently across the document. The mode governs "
    "structure, point of view and stance; it never overrides factual specificity."
)

PRECEDENCE = (
    "PRECEDENCE: tone governs diction, rhythm and formality. Narrative governs structure, "
    "point of view and stance. If they pull apart, keep the narrative's structure and "
    "express it inside the tone's register; never drop either axis. Never mention the "
    "axes or the conflict inside the text."
)

STYLE_ONLY = (
    "The examples below teach style only. Do not reuse their topics, names, facts, "
    "openings or wording. Your subject comes from the plan and section specification."
)


@lru_cache(maxsize=8)
def _load_library(path_str: str, mtime_ns: int) -> dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def library(cfg: Config) -> dict[str, Any]:
    path = Path(cfg.prompts_dir) / "style_shots.yaml"
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return {}
    return _load_library(str(path), mtime)


def tone_directive(cfg: Config, tone: str) -> str:
    entry = (library(cfg).get("tones") or {}).get(tone) or {}
    return str(entry.get("directive") or DEFAULT_TONE_DIRECTIVE).strip()


def narrative_directive(cfg: Config, narrative: str) -> str:
    entry = (library(cfg).get("narratives") or {}).get(narrative) or {}
    return str(entry.get("directive") or DEFAULT_NARRATIVE_DIRECTIVE).strip()


def _shot(label: str, shot: dict[str, Any]) -> str:
    return (
        f"[{label}]\n"
        f"REQUEST: {str(shot.get('input', '')).strip()}\n"
        f"RESPONSE: {str(shot.get('output', '')).strip()}"
    )


def priming_block(cfg: Config, style: dict[str, str], max_chars: int = 3200) -> str:
    """Render directives and contrastive exemplars for section/passage prompts."""
    tone = style.get("tone", "neutral_explanatory")
    narrative = style.get("narrative", "expository")
    lib = library(cfg)
    parts = [
        f"TONE — {tone}: {tone_directive(cfg, tone)}",
        f"NARRATIVE — {narrative}: {narrative_directive(cfg, narrative)}",
        PRECEDENCE,
        STYLE_ONLY,
    ]
    tone_shot = ((lib.get("tones") or {}).get(tone) or {}).get("example")
    if tone_shot:
        parts.append(_shot(f"TONE EXAMPLE: {tone} | NARRATIVE: expository", tone_shot))
    narrative_shot = ((lib.get("narratives") or {}).get(narrative) or {}).get("example")
    if narrative_shot and narrative != "expository":
        parts.append(_shot(f"TONE: neutral_explanatory | NARRATIVE EXAMPLE: {narrative}", narrative_shot))
    composed = (lib.get("composed") or {}).get(f"{tone}|{narrative}")
    if composed:
        parts.append(_shot(f"COMPOSED EXAMPLE: {tone} x {narrative}", composed))
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        # keep every directive and the tone shot; trim from the last examples first
        text = text[:max_chars].rsplit("\n\n", 1)[0] + "\n\n[examples truncated]"
    return text


def style_fields(cfg: Config, style: dict[str, str]) -> dict[str, str]:
    """Prompt variables shared by blueprint, passage and section templates."""
    return {
        "tone": style.get("tone", "neutral_explanatory"),
        "narrative": style.get("narrative", "expository"),
        "tone_directive": tone_directive(cfg, style.get("tone", "neutral_explanatory")),
        "narrative_directive": narrative_directive(cfg, style.get("narrative", "expository")),
        "style_priming": priming_block(cfg, style),
    }
