"""Anchor as a Harness² BenchmarkAdapter.

Mapping onto the Harness² method:
  task            one brand run (a frozen TaskPack)
  domain          the industry playbook (saas, hospitality, ecommerce, ...): the experience
                  library is per industry, so lessons from one hotel guide the next hotel
  source          pack/source/{brand.md,evidence.md}: what the selector checks claims against,
                  plus market.md (DataForSEO competitors, searches, content gaps) when configured
  execute         one rollout of anchor.generate with a candidate harness tree
  trajectory      the rollout's [ACTION]/[OBSERVATION]/[ERROR] log
  deliverable     posts.md (verified posts only)
  validate_tree   executor invariants (no scripts/plugins/sub_agents; valid skill frontmatter)
"""

from __future__ import annotations

from pathlib import Path

from harness2.core.spec import BenchPrompts, BenchSpec, ChannelSpec
from harness2.substrate.opencode import OpencodeSubstrate

from .. import generate, harness
from ..config import Settings
from ..models import TaskPack
from ..prepare import load_pack

PROMPTS = BenchPrompts(
    work=(
        "Turn a company's frozen evidence pack (its rendered website plus press coverage, split "
        "into numbered evidence items) into evidence-grounded LinkedIn and Instagram posts. When "
        "source/market.md exists it holds search-data market context (organic competitors, what the "
        "audience searches for, topics competitors rank for and the brand does not); it steers fact "
        "choice and angle but is never evidence. Each "
        "run loads the industry skill, selects post-worthy facts that each carry a verbatim quote "
        "from a cited evidence item, writes channel-native posts per fact, and passes "
        "deterministic grounding checks (verbatim quote, every number present in cited evidence, "
        "banned phrases, length and format) plus an independent claim check by a second model. "
        "Failing posts get bounded repairs and are dropped if still failing; posts.md holds only "
        "the posts that passed."
    ),
    domain_word="industry",
    deliverable_word="post set",
    inv_levers=(
        "This executor is a fixed pipeline with no shell or tool loop: files under scripts/, "
        "sub_agents/ and plugin/ are never run and are rejected at validation. Procedure is "
        "steered by guardrails.md and tool_descriptions/tool_guidance.md, which every stage reads. "
        "Look in trajectories for REJECTED facts (quote not verbatim, metric or entity missing from "
        "the cited item), DROPPED posts and problems that recur across repair attempts; encode the "
        "procedure that prevents them (how to copy quotes, how to pick citable facts, how to "
        "answer repair feedback, what to do when evidence is thin)."
    ),
    dom_levers=(
        "Practitioner knowledge lives in skills/<industry>/SKILL.md: which facts this industry's "
        "audience acts on, what LinkedIn and Instagram readers in it expect, industry claim rules "
        "(awards, prices, capacities, compliance), and the `banned_phrases` YAML list in the "
        "frontmatter, which code enforces. Keep the frontmatter keys name, description, industry, "
        "keywords, schema_types, crawl_paths and news_queries valid: they route and crawl future "
        "runs. A new skill without `industry: true` is offered to every run as an optional skill "
        "and loaded when its description's trigger applies. Market context (source/market.md) "
        "shows which differentiators and search intents matter in this industry: encode the "
        "industry-level pattern (e.g. which kinds of facts stand out against typical competitors, "
        "how to echo search intent in hooks and hashtags), never this brand's competitors, "
        "keywords or facts."
    ),
    yardstick=(
        "A strong run turns specific, recent, third-party-confirmed facts into posts the "
        "industry's audience would save or share, states nothing the evidence does not, and "
        "publishes fewer posts rather than padding when evidence is thin."
    ),
    domain_guidance=(
        "Industries differ in what counts as proof: SaaS buyers act on named customers, measured "
        "outcomes, integrations and security credentials; hotel guests and event planners act on "
        "awards, dining, rooms, capacities, location and dated offers; shoppers act on product "
        "specifics, reviews, materials and launches. LinkedIn rewards a strong first line and "
        "operator-to-operator substance; Instagram rewards a sensory, concise caption."
    ),
    selection_checks=(
        "Every number, name, date, price, award and superlative in a post must appear in "
        "context/source/evidence.md under one of the evidence ids that post lists; an invented "
        "detail disqualifies the post set. Prefer the set with more VERIFIED posts only when they "
        "are equally faithful. A post must not name or compare to a competitor from "
        "context/source/market.md unless its cited evidence does; among faithful sets, prefer the "
        "one whose posts better show what sets the brand apart and speak to what its audience "
        "searches for. Each post must name the brand, open LinkedIn with a hook line that "
        "works before 'see more', and read as native to its channel without clichés."
    ),
)


class AnchorAdapter:
    def __init__(self, run_dir: Path, pack: TaskPack, cfg: Settings, base_harness: Path):
        self.cfg = cfg
        self.pack = pack
        self.pack_dir = run_dir / "pack"
        self._base = base_harness
        self.substrate = OpencodeSubstrate()
        channel = ChannelSpec("opencode", f"llm/{cfg.proposer_model}")
        self.spec = BenchSpec(
            name="anchor",
            runs_root=run_dir / "h2",
            install_mode="workspace_config",
            prompts=PROMPTS,
            channels={"proposer": channel, "selector": ChannelSpec("opencode", f"llm/{cfg.selector_model}")},
            domain_word="industry",
        )

    # -- task ----------------------------------------------------------------------------

    def tasks(self, split: str = "all") -> list[str]:
        return [self.pack.task_id]

    def domain_of(self, task_id: str) -> str:
        return self.pack.industry

    def task_prompt(self, task_id: str) -> str:
        b = self.pack.brand
        return (
            f"Write up to {self.pack.max_posts} social posts for {b.name} ({b.url}), each with a "
            "LinkedIn post and an Instagram caption plus poster copy, grounded ONLY in the evidence "
            "pack in source/ (brand.md, evidence.md; market.md, if present, is positioning context, "
            "not evidence). Every factual claim must trace to a cited "
            "evidence id; anything unverifiable is left out. Deliver posts.md listing each verified "
            "post with its LinkedIn text, Instagram caption, hashtags, poster copy and sources."
        )

    def task_files(self, task_id: str) -> Path:
        return self.pack_dir / "source"

    def base_harness(self) -> Path:
        return self._base

    def validate_tree(self, tree: dict[str, str]) -> None:
        import tempfile

        from harness2.core import tree as htree

        with tempfile.TemporaryDirectory() as tmp:
            htree.write_tree(self.substrate.surface(), tree, Path(tmp), stubs=False)
            errs = harness.problems(tmp)
            if self.pack.industry not in harness.load(tmp).skills:
                errs.append(f"skills/{self.pack.industry}/SKILL.md (this task's industry skill) must stay")
        if errs:
            raise ValueError(" | ".join(errs))

    # -- rollouts ------------------------------------------------------------------------

    def execute(self, task_id: str, harness_dir: Path | None, run_id: str, *, timeout: int | None = None) -> Path:
        run_dir = self.spec.runs_root / "rollouts" / run_id
        if (run_dir / "DONE").is_file():
            return run_dir
        generate.generate(load_pack(self.pack_dir), Path(harness_dir or self._base), run_dir, self.cfg)
        return run_dir

    def delivered(self, run_dir: Path) -> bool:
        cards = Path(run_dir) / "cards.json"
        return cards.is_file() and '"status": "verified"' in cards.read_text(encoding="utf-8")

    def trajectory(self, run_dir: Path, *, obs_trunc: int) -> str:
        p = Path(run_dir) / "trajectory.md"
        text = p.read_text(encoding="utf-8") if p.is_file() else "(no trajectory written)"
        return "\n".join(line if len(line) <= obs_trunc else line[:obs_trunc] + " ...[renderer truncated]"
                         for line in text.splitlines())

    def deliverable_text(self, run_dir: Path) -> str:
        p = Path(run_dir) / "posts.md"
        return p.read_text(encoding="utf-8") if p.is_file() else ""

    def deliverable_files(self, run_dir: Path) -> dict[str, str]:
        text = self.deliverable_text(run_dir)
        return {"posts.md": text} if text else {}
