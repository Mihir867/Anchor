"""A Harness² Proposer for any chat model (Groq, Ollama, vLLM, ...), no agent CLI required.

Stock Harness² improvers are agentic CLIs (OpenCode / Claude Code) that open files in a
`context/` workspace and edit `context/harness/` in place. A plain chat model cannot use
tools, so this proposer gives it the same workspace by value:

  * the context tree is inlined (task, harness, trajectories, deliverables, pool, library,
    source) under a character budget, harness first and source last;
  * edits come back as whole-file blocks, applied to a copy of `context/harness/` that is then
    harvested exactly like the stock proposer harvests an agent's workspace.

Everything else -- missions, retries on rejected trees, audit files, caching -- is inherited
from `harness2.core.proposer.Proposer`, so the method itself is unchanged.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from harness2.core.proposer import Proposer, ProposerError, Reply, _call_fingerprint

from ..llm import LLM, LLMError

EDIT_PROTOCOL = """You are a harness improver working through a text-only interface.
The files of `context/` are inlined in the message below (they are the workspace an agent
would open). You cannot run tools. To change the harness, emit each changed or new file IN FULL:

<file path="context/harness/RELATIVE/PATH.md">
...the complete new file content...
</file>

To delete a file: <delete path="context/harness/RELATIVE/PATH.md"/>
Files you do not emit stay exactly as they are. Only paths under context/harness/ are applied.
Put all file blocks first, then the single <notes> block the job asks for. If you decide
KEEP_BASE, emit no file blocks."""

READ_PROTOCOL = """The files of `context/` are inlined in the message below; you cannot run tools,
so read them there. Answer in exactly the output format the job specifies."""

_FILE = re.compile(r'<file\s+path="([^"]+)">\n?(.*?)</file>', re.S)
_DELETE = re.compile(r'<delete\s+path="([^"]+)"\s*/>')
_BULKY = re.compile(r"^(pool/[^/]+/harness/|library/.*/harness/)")
_TEXT_SUFFIX = {".md", ".txt", ".json", ".yaml", ".yml", ".diff", ".py", ".ts", ""}

# (prefix, per-file cap, share of budget) in priority order.
_SECTIONS = [
    ("task.md", 8000, 0.08),
    ("harness/", 24000, 0.25),
    ("candidates/", 14000, 0.30),
    ("decisions/", 3000, 0.04),
    ("rollouts/", 16000, 0.22),
    ("deliverables/", 9000, 0.14),
    ("pool/", 9000, 0.22),
    ("library/", 6000, 0.08),
    ("adoption", 4000, 0.03),
    ("base_harness/", 8000, 0.06),
    ("source/", 30000, 0.25),
]


def pack_context(root: Path, budget: int) -> str:
    files = [p for p in sorted(root.rglob("*")) if p.is_file() and p.suffix.lower() in _TEXT_SUFFIX
             and "images" not in p.parts and "raw" not in p.parts]
    rel = {p: p.relative_to(root).as_posix() for p in files}
    # Candidate harness copies are summarised by their harness.diff; library trees by INDEX.md
    # and EXPERIENCE.md. Their full copies are listed, not inlined.
    done: set[Path] = {p for p in files if _BULKY.match(rel[p])}
    out: list[str] = []
    remaining = budget
    for prefix, cap, share in _SECTIONS:
        group = [p for p in files if p not in done and rel[p].startswith(prefix)]
        allowance = int(budget * share)
        for p in group:
            done.add(p)
            body = p.read_text(encoding="utf-8", errors="replace")
            limit = min(cap, allowance, remaining)
            if limit <= 200:
                out.append(f'<context_file path="context/{rel[p]}">(omitted: budget exhausted, '
                           f"{len(body):,} chars)</context_file>")
                continue
            if len(body) > limit:
                body = body[:limit] + f"\n...[renderer truncated {len(body) - limit:,} chars]"
            out.append(f'<context_file path="context/{rel[p]}">\n{body}\n</context_file>')
            allowance -= len(body)
            remaining -= len(body)
    rest = [p for p in files if p not in done or _BULKY.match(rel[p])]
    if rest:
        out.append("Other files present (not inlined): " + ", ".join(f"context/{rel[p]}" for p in rest[:40]))
    return "# INLINED CONTEXT FILES\n\n" + "\n\n".join(out)


def apply_edits(text: str, harness_dir: Path) -> list[str]:
    """Apply file/delete blocks to `harness_dir`; return the paths that were ignored."""
    ignored: list[str] = []
    for path, _ in [(m.group(1), None) for m in _DELETE.finditer(text)]:
        target = _target(path, harness_dir)
        if target and target.is_file():
            target.unlink()
        elif not target:
            ignored.append(path)
    for m in _FILE.finditer(text):
        target = _target(m.group(1), harness_dir)
        if not target:
            ignored.append(m.group(1))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(m.group(2).rstrip() + "\n", encoding="utf-8")
    return ignored


def _target(path: str, harness_dir: Path) -> Path | None:
    p = path.strip().lstrip("./")
    for prefix in ("context/harness/", "harness/"):
        if p.startswith(prefix):
            rel = p[len(prefix):]
            if rel and ".." not in rel.split("/"):
                return harness_dir / rel
    return None


@dataclass
class LLMProposer(Proposer):
    llm: LLM | None = None
    context_chars: int = 90000

    def call(self, mission, context_dir, label, *, system="", timeout=None, max_attempts=None,
             harvest=None) -> Reply:
        key = _call_fingerprint(label, mission, system, context_dir)
        cached = self._cached(label, key, require_workspace=bool(harvest))
        if cached is not None:
            self._calls.append(cached)
            return cached
        if self.llm is None:
            raise ProposerError(f"[{label}] LLMProposer has no model configured")
        tries = max(1, int(self.attempts if max_attempts is None else max_attempts))
        tmp = Path(tempfile.mkdtemp(prefix="anchor-h2-"))
        try:
            ctx = tmp / "context"
            if context_dir and Path(context_dir).is_dir():
                shutil.copytree(context_dir, ctx, dirs_exist_ok=True)
            user = mission + "\n\n" + pack_context(ctx, self.context_chars)
            sys_prompt = (EDIT_PROTOCOL if harvest else READ_PROTOCOL) + (f"\n\n{system}" if system else "")
            last = ""
            for attempt in range(1, tries + 1):
                try:
                    text = self.llm.complete(sys_prompt, user, temperature=0.4)
                except LLMError as exc:
                    last = str(exc)
                    continue
                if not text.strip():
                    last = "empty reply"
                    continue
                reply = Reply(label=label, text=text, ok=True, attempts=attempt, channel="llm")
                if harvest:
                    ignored = apply_edits(text, ctx / "harness")
                    if ignored:
                        reply.text += "\n\n(ignored edits outside context/harness/: " + ", ".join(ignored) + ")"
                    reply.workspace = self._harvest(tmp, harvest, label, key)
                self._write_audit(reply, mission, system, key)
                self._calls.append(reply)
                return reply
            raise ProposerError(f"[{label}] llm/{self.llm.model}: {last}", attempts=tries)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
