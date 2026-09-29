"""Locate the bundled skill and read/write the `fleet_version` stamp in its frontmatter."""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

SKILL_REL = Path(".claude") / "skills" / "fleet"
_STAMP_RE = re.compile(r'^fleet_version:\s*"?([^"\n]+)"?\s*$', re.MULTILINE)


def bundled_skill_dir() -> Path:
    """The skill shipped in the wheel, or — running from a source checkout — the repo's copy."""
    packaged = resources.files("fleet") / "skill"
    if packaged.is_dir():
        return Path(str(packaged))
    return Path(__file__).resolve().parent.parent / SKILL_REL


def read_stamp(skill_md: str) -> str:
    match = _STAMP_RE.search(skill_md.split("\n---", 1)[0])
    return match.group(1).strip() if match else ""


def stamp(skill_md: str, version: str) -> str:
    line = f'fleet_version: "{version}"'
    if not skill_md.startswith("---\n"):
        raise ValueError("SKILL.md has no frontmatter")
    head, sep, body = skill_md[4:].partition("\n---")
    head = _STAMP_RE.sub(line, head) if _STAMP_RE.search(head) else f"{head}\n{line}"
    return f"---\n{head}{sep}{body}"
