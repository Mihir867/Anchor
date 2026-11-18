"""Read a Harness² component tree and turn it into model context.

The tree is the ONLY place behaviour lives that Harness² may edit:

    systemprompt.md                 c1  role, voice, the grounding contract
    guardrails.md                   c2  non-negotiables + skill trigger lines
    LongTermMEMORY.md               c3  short universal facts for every run
    tool_descriptions/tool_guidance.md  c4  how the pipeline's stages and checks behave
    skills/<name>/SKILL.md          c6  on-demand practitioner playbooks (one per industry,
                                         plus any the improver adds)

Output schemas, the evidence format and the deterministic checks stay in code: they are the
contract the rest of the system depends on, so the improver tunes behaviour, never plumbing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ALWAYS_ON = (
    "systemprompt.md",
    "guardrails.md",
    "LongTermMEMORY.md",
    "tool_descriptions/tool_guidance.md",
)


@dataclass
class Skill:
    name: str
    description: str
    meta: dict
    body: str

    def list_meta(self, key: str) -> list[str]:
        value = self.meta.get(key) or []
        return [str(v) for v in value] if isinstance(value, list) else [str(value)]


@dataclass
class Harness:
    root: Path
    always_on: dict[str, str] = field(default_factory=dict)
    skills: dict[str, Skill] = field(default_factory=dict)

    def context(self, skill_names: list[str]) -> str:
        parts = [self.always_on[name].strip() for name in ALWAYS_ON if self.always_on.get(name, "").strip()]
        for name in skill_names:
            skill = self.skills.get(name)
            if skill:
                parts.append(f"# LOADED SKILL: {name}\n\n{skill.body.strip()}")
        return "\n\n---\n\n".join(parts)

    def banned_phrases(self, skill_names: list[str]) -> list[str]:
        out: list[str] = []
        for name in skill_names:
            if name in self.skills:
                out += self.skills[name].list_meta("banned_phrases")
        return out


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    try:
        meta = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"frontmatter is not valid YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    return meta, text[end + 4 :].lstrip("\n")


def load(root: Path | str) -> Harness:
    root = Path(root)
    h = Harness(root=root)
    for name in ALWAYS_ON:
        p = root / name
        h.always_on[name] = p.read_text(encoding="utf-8") if p.is_file() else ""
    for skill_md in sorted((root / "skills").glob("*/SKILL.md")):
        meta, body = split_frontmatter(skill_md.read_text(encoding="utf-8"))
        name = skill_md.parent.name
        h.skills[name] = Skill(name=name, description=str(meta.get("description", "")), meta=meta, body=body)
    return h


def problems(root: Path | str) -> list[str]:
    """Executor-specific invariants, phrased as actionable feedback for the improver."""
    root = Path(root)
    errs: list[str] = []
    if not (root / "systemprompt.md").is_file() or not (root / "systemprompt.md").read_text().strip():
        errs.append("systemprompt.md must exist and be non-empty")
    for kind in ("scripts", "sub_agents", "plugin"):
        files = [p for p in (root / kind).rglob("*") if p.is_file() and p.name != "README.md"] if (root / kind).is_dir() else []
        if files:
            errs.append(
                f"{kind}/ is not executed by this pipeline (it has no tool loop), so "
                f"{[p.name for p in files][:3]} would be dead weight. Put procedure in "
                "tool_descriptions/tool_guidance.md or guardrails.md, and practitioner knowledge in "
                "skills/<name>/SKILL.md"
            )
    for skill_md in sorted((root / "skills").glob("*/SKILL.md")):
        try:
            meta, body = split_frontmatter(skill_md.read_text(encoding="utf-8"))
        except ValueError as exc:
            errs.append(f"{skill_md.relative_to(root)}: {exc}")
            continue
        if not str(meta.get("description", "")).strip():
            errs.append(f"{skill_md.relative_to(root)} needs a description in its frontmatter")
        bp = meta.get("banned_phrases")
        if bp is not None and not isinstance(bp, list):
            errs.append(f"{skill_md.relative_to(root)}: banned_phrases must be a YAML list")
        if len(body) > 12000:
            errs.append(f"{skill_md.relative_to(root)} body is {len(body)} chars; keep skills under 12000")
    return errs
