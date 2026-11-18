# Anchor AI Engine

Give it a company URL. It crawls the site and the press, extracts citable evidence, writes
LinkedIn and Instagram posts in which every claim traces to that evidence, renders 1080×1350
branded posters, and writes everything to `posts.md`. Posts that can't be grounded are dropped,
not shipped.

[Harness²](https://github.com/google-research/harness2) (Google Research) refines the
model's *harness* (prompts, guardrails, skills) for each brand, and keeps per-industry lessons
so later runs in the same industry start better. This works with plain open-weight models; no
fine-tuning is involved.

## Quick start

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/playwright install chromium        # or have Google Chrome installed
# .env (here or in the parent dir): GROQ_KEY=... (or ANCHOR_API_KEY + ANCHOR_BASE_URL)

.venv/bin/python run.py https://kiro.dev                 # one rollout with the best learned harness (cheap)
.venv/bin/python run.py https://kiro.dev --refine        # Harness² Propose-Probe-Compose (~5x tokens)
.venv/bin/python run.py https://hotel.example --industry hospitality --refine --k 2
.venv/bin/python -m pytest tests                         # offline, no API calls
```

Output goes to `runs/<domain>-<timestamp>/output/`: `posts.md`, and for each post a 3-slide
carousel (`post_N_1.png` cover with logo, title and image; `post_N_2..3.png` explainer slides;
`post_N_carousel.pdf` for LinkedIn document posts), plus `deck.json`,
`report.md` (what was verified, what was dropped and why), `trajectory.md`, and `harness/`
(the exact harness that produced it).

## Architecture

```
URL ──► prepare (deterministic, once per run) ─────────────────────► TaskPack (frozen)
          crawl.py     Playwright: tokens, logo, screenshot, ≤14 rendered pages
          extract.py   pages → evidence items [E1..En] (+ JSON-LD, reviews, pricing, logos)
          research.py  press → evidence items (must mention the brand)
          classify     skill keywords + schema.org types; LLM only on ties

TaskPack + harness/ ──► generate.py  (the executor: one "rollout")
          1 load skills named by the harness for this industry
          2 mine facts in evidence batches → each needs evidence ids + a verbatim quote
              ✔ code: quote is an exact span, metrics/entities are in the cited items, fact is about the brand
          3 write LinkedIn + Instagram + poster copy per fact
              ✔ code: every number in cited evidence, banned phrases, lengths, brand named
              ✔ critic: a DIFFERENT model family checks each claim against the evidence
              ✗ → targeted repair with the exact problems (≤2), then drop
          4 posts.md (verified only) + cards.json + trajectory.md

refine (Harness², h2/) ──► Propose-Probe-Compose over harness/, rollouts via generate.py
          base rollout → INV (procedure) + DOM (industry knowledge) edits → probed
          → composed harness → rolled → blind selection (k≥2) → lesson → runs/library/<industry>/

finalize ──► render.py posters from real brand imagery + fonts → output/
```

What is editable and what is fixed:

| Lives in `harness/` (Harness² may edit) | Lives in code (fixed contract) |
|---|---|
| `systemprompt.md`: role, grounding contract, voice | output schemas (`models.py`) |
| `guardrails.md`: non-negotiables, skill triggers | deterministic checks (`verify.py`) |
| `LongTermMEMORY.md`: platform facts | evidence format, crawl, rendering |
| `tool_descriptions/tool_guidance.md`: how checks behave | the critic's independence |
| `skills/<industry>/SKILL.md`: practitioner playbooks | |

The improver can therefore tune *how the model works*, but it can never weaken the checks
that decide what ships.

### Why this gets good results from open-source models

- **Small, single-purpose calls.** Pick facts, then write per fact, then critique. There is no
  mega-prompt.
- **Evidence ids and verbatim quotes**, so grounding is checked by code and not by vibes.
- **Schema-validated JSON**, with validation errors fed back to the model for repair.
- **A critic from another model family** (`qwen` checking `gpt-oss`), so the writer doesn't
  grade itself.
- **Fail-closed checks.** A missing score is a failure, never a pass.
- **Harness²**, which adapts the harness from the model's own trajectories and accumulates
  industry lessons.

## Adding an industry

Create `harness/skills/<name>/SKILL.md` with this frontmatter and a practitioner body (see
`hospitality`):

```yaml
---
name: <name>                 # must match the directory
description: <one line: who it is for>
industry: true
keywords: [...]              # whole-word matches on the homepage
schema_types: [...]          # schema.org @types that signal this industry
crawl_paths: [...]           # pages worth rendering first
news_queries: ['"{brand_name}" (...) {current_year}']
banned_phrases: [...]        # enforced in code
---
```

Then add a trigger line to `guardrails.md` ("When …, load the `<name>` skill."). Routing,
crawling, writing, checking and the Harness² library all pick it up automatically.

## Models and endpoints

Each role has its own model spec in the form `provider:model`. Specs whose provider has no key
in `.env` are skipped. Each role falls back through `ANCHOR_FALLBACK_MODELS` (set it to `none`
to disable). A daily-quota 429 trips a circuit breaker, so later calls skip that model at once.

| Provider prefix | Key in `.env` | Notes |
|---|---|---|
| `groq:` | `GROQ_API_KEY` / `GROQ_KEY` | free tier: 8k tokens/min, 200k/day per model |
| `cerebras:` | `CEREBRAS_API_KEY` | open-weight models (gpt-oss, Qwen, Llama) |
| `openrouter:` | `OPENROUTER_API_KEY` | many open-weight models, some free |
| `together:` | `TOGETHER_API_KEY` | open-weight models |
| `gemini:` | `GEMINI_API_KEY` | Gemini / Gemma via the OpenAI-compatible endpoint |
| `ollama:` | none (`OLLAMA_HOST`) | local; native API with the context window sized per request |
| no prefix | `ANCHOR_BASE_URL` + `ANCHOR_API_KEY` | any other OpenAI-compatible server (vLLM, LM Studio) |

| Variable | Default | Role |
|---|---|---|
| `ANCHOR_MODEL` | `groq:openai/gpt-oss-120b` | miner and writer |
| `ANCHOR_CRITIC_MODEL` | `groq:qwen/qwen3.8-27b` | independent claim check (different family) |
| `ANCHOR_PROPOSER_MODEL` | `groq:openai/gpt-oss-120b` | Harness² improver |
| `ANCHOR_SELECTOR_MODEL` | `groq:qwen/qwen3.8-27b` | Harness² blind selection (k≥2) |

**Budget for Harness².** A refine run at k=1 is 4 full rollouts plus 3–4 improver calls:
roughly **350–400k tokens**, and single improver requests of about 12–20k tokens. The Groq
free tier (8k/min, 200k/day) cannot hold one. Before refining, the engine probes the
improver's endpoint. If its per-minute limit is below `ANCHOR_REFINE_MIN_TPM`, or its daily
quota is spent, it runs one rollout instead and says so in `report.md`.

## Cost

- **Refine once, reuse often.** `--refine` runs Harness² (4 rollouts plus improver calls, about
  5× a normal run). When it adopts a harness and records a lesson, that harness goes into
  `runs/library/agg/<industry>/`. Every later normal run in that industry uses the newest
  valid one automatically, so you pay for refinement occasionally rather than on every brand.
- **Free first.** `.env` routes each role through Groq's free tier first. Paid Cerebras credits
  are used only when Groq is rate-limited, out of daily quota, or the request is too large.
- **No paying for invisible reasoning.** Qwen runs with reasoning off and gpt-oss on `low`.
  Reasoning tokens are billed as output: with reasoning on, one writer call spent its whole
  3,000-token budget reasoning and returned nothing. A reply cut off before any content moves
  to the next model instead of being retried.
- **Every run reports its tokens** per model in `report.md` and `result.json`.

## Scaling

- **Runs are isolated.** Each run gets its own `runs/<id>/`, with no shared mutable files.
  The only cross-run state is `runs/library/` (Harness² lessons, per industry).
- **Rollouts are independent** and keyed by the frozen pack, so they parallelise and resume.
- **The API** (`main.py`) is job-based: `POST /runs` returns a `job_id`, then poll
  `GET /runs/{id}`. To scale horizontally, swap the in-process job dict and thread pool for
  Redis/RQ or Celery, and put `runs/` on shared storage or S3.
