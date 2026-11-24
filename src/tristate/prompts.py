"""Versioned prompt files.

Prompts live on disk with a YAML front-matter block so every call can record the
exact prompt version that produced an artefact. Editing a prompt changes its
version hash, which changes the config/output fingerprint and forces re-runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class PromptError(RuntimeError):
    pass


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    stage: str
    description: str
    body: str
    source_hash: str
    path: str

    @property
    def full_version(self) -> str:
        return f"{self.version}+{self.source_hash[:8]}"

    def placeholders(self) -> set[str]:
        return set(_PLACEHOLDER.findall(self.body))

    def render(self, **variables: object) -> str:
        missing = self.placeholders() - set(variables)
        if missing:
            raise PromptError(
                f"prompt {self.name} missing variables: {sorted(missing)}"
            )
        rendered = _PLACEHOLDER.sub(lambda m: str(variables[m.group(1)]), self.body)
        if "{{" in rendered or "}}" in rendered:
            raise PromptError(f"prompt {self.name} has unresolved placeholders")
        return rendered


def _parse_front_matter(text: str, path: Path) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise PromptError(f"{path}: missing front matter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise PromptError(f"{path}: malformed front matter")
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    for key in ("version", "stage"):
        if key not in meta:
            raise PromptError(f"{path}: front matter missing '{key}'")
    return meta, body


class PromptLibrary:
    """Loads and caches prompts from a directory."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self._prompts: dict[str, Prompt] = {}
        self._mtimes: dict[str, float] = {}
        self.reload()

    def reload(self) -> None:
        if not self.directory.exists():
            raise PromptError(f"prompt directory not found: {self.directory}")
        for path in sorted(self.directory.glob("*.md")):
            meta, body = _parse_front_matter(path.read_text(encoding="utf-8"), path)
            from .util import sha256_text

            prompt = Prompt(
                name=path.stem,
                version=str(meta["version"]),
                stage=str(meta["stage"]),
                description=str(meta.get("description", "")),
                body=body,
                source_hash=sha256_text(body + str(meta)),
                path=str(path),
            )
            self._prompts[prompt.name] = prompt
            self._mtimes[prompt.name] = path.stat().st_mtime
        if not self._prompts:
            raise PromptError(f"no prompts found in {self.directory}")

    def get(self, name: str) -> Prompt:
        p = self._prompts.get(name)
        if p is None:
            raise PromptError(f"unknown prompt: {name} (have: {sorted(self._prompts)})")
        return p

    def names(self) -> list[str]:
        return sorted(self._prompts)

    def versions(self) -> dict[str, str]:
        return {n: p.full_version for n, p in sorted(self._prompts.items())}

    def render(self, name: str, **variables: object) -> tuple[str, str]:
        """Return (rendered_text, full_prompt_version)."""
        p = self.get(name)
        return p.render(**variables), p.full_version
