# ai-trends-digest

> Daily AI trends digest: GitHub Actions runs Claude Code headless, then emails
> the result.

| | |
|---|---|
| Sources | GitHub Trending (daily + weekly), Medium tag feeds, WebSearch, OpenRouter model prices, Artificial Analysis Intelligence Index |
| Focus | AI, AI agents, agent harnesses, skills, plugins, MCP, coding agents, model prices |
| Schedule | 05:00 UTC daily, dispatched by [gh-workflow-scheduler](https://github.com/teodorio95-portofolio/gh-workflow-scheduler) |
| Delivery | `digests/YYYY-MM-DD.md` on branch `digests`, email (Gmail SMTP) |
| Auth | Claude subscription token (`claude setup-token`), no API billing |

```mermaid
flowchart LR
  worker[Cloudflare Worker 05:00 UTC] -->|workflow_dispatch| wf[digest.yml]
  wf --> or[openrouter_prices.py]
  wf --> cc[Claude Code -p]
  cc --> src[GitHub Trending, Medium RSS, WebSearch]
  wf --> aa[aa_models.py]
  or --> cc
  aa --> cc
  cc --> md[digests/DATE.md]
  md --> branch[branch digests]
  md --> mail[Email] --> inbox[Inbox]
```

## Secrets

| Secret | What |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | output of `claude setup-token` |
| `MAIL_USERNAME` | Gmail address, sender and recipient |
| `MAIL_PASSWORD` | Gmail app password (needs 2-Step Verification) |
| `ARTIFICIAL_ANALYSIS_API_KEY` | free key from artificialanalysis.ai (1000 requests/day) |

Set each with `gh secret set <NAME> -R teodorio95-portofolio/ai-trends-digest`
(it prompts without echoing). Run by hand: `gh workflow run digest.yml -f force=true`.

## Layout

- `.github/workflows/digest.yml` — the whole pipeline; Claude Code only writes
  the Markdown file, commit and email are plain workflow steps.
- `prompt/digest.md` — the instructions Claude Code gets (`{{TODAY}}`,
  `{{OPENROUTER}}` and `{{AA_MODELS}}` are filled in by the workflow).
- `scripts/openrouter_prices.py` — stdlib-only; snapshots OpenRouter prices to
  `data/openrouter-models.json` and prints price drops, per-provider discounts,
  new/free models, ending free offers and retired models.
- `scripts/aa_models.py` — stdlib-only; ranks closed frontier models
  (Anthropic, OpenAI, Google, xAI, Meta; open families like gpt-oss, Gemma,
  Llama dropped), newest version per model line (a newer version without an
  index yet is listed, not ranked), one effort variant per model, from the free
  Artificial Analysis API (`/api/v2/language/models/free`) by Intelligence
  Index, index per blended $ (3:1 input:output, computed from the in/out
  prices), and output speed (the last two only among models within 80% of the
  best index); snapshot in `data/aa-models.json` marks new entries.
- `tests/` — `uv run --no-project --with pytest pytest -q tests`.
- Branch `digests` — one Markdown file per day plus the price snapshot; the
  agent reads the last 7 days to report only what is new.

> ⚠️ OpenRouter's `/models` always reports `discount: 0`; real discounts are per
> provider on `/models/{id}/endpoints`. Artificial Analysis no longer publishes a
> per-model coding index (the API field is always null); coding is a quarter of
> Intelligence Index v5. Prices are per 1M tokens: the Coding Agent Index page
> (agent + model, cost per task) has no API, so the digest only links it.
