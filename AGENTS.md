# ai-trends-digest — agent context

Daily AI trends digest (agents, harnesses, skills, MCP, coding agents, model
prices): Claude Code runs headless in CI, writes one Markdown file, the workflow
commits and emails it. Runs on: GitHub Actions (public repo), dispatched daily.

## Commands
- No Makefile and no `pyproject.toml`; scripts are stdlib-only Python.
- Tests: `uv run --no-project --with pytest pytest -q tests` (safe, offline).
- Lint config: `ruff.toml` (line length 120, rules E, F, I, UP, B).
- Manual run: `gh workflow run digest.yml -f force=true` — sends a real email
  and commits to branch `digests`; `-f resend_email=true` re-sends today's
  email only (no Claude run, no commit). Do not trigger casually.

## Layout
- `.github/workflows/digest.yml` — the whole pipeline.
- `prompt/digest.md` — instructions for Claude Code; `{{TODAY}}`,
  `{{OPENROUTER}}`, `{{AA_CODING}}` are substituted by `sed` in the workflow.
- `scripts/openrouter_prices.py` — OpenRouter price snapshot and diff.
- `scripts/aa_coding.py` — Artificial Analysis coding-index ranking.
- `scripts/email_html.py` — Markdown digest to HTML / `--text` email body.
- `tests/` — pytest for the three scripts.
- Branch `digests` — `digests/YYYY-MM-DD.md` plus `data/*.json` snapshots.

## How it works
- No `schedule` trigger: gh-workflow-scheduler fires `workflow_dispatch` at
  05:00 UTC. Job timeout 25 min, `concurrency: digest`.
- Branch `digests` is checked out into `out/`; if today's file exists and
  `force` is false, the run does nothing.
- Deterministic steps first: `openrouter_prices.py` and `aa_coding.py` write
  Markdown to `$RUNNER_TEMP`; a fetch failure becomes a text note, not a failure.
- `claude -p` (pinned `@anthropic-ai/claude-code` version, tools limited to
  Read/Write/Edit/Glob/Grep/WebFetch/WebSearch) writes only
  `out/digests/<date>.md`, in Romanian; it reads the last 7 digests to skip repeats.
- Commit/push to `digests` and Gmail SMTP email are plain workflow steps.
- Secrets: `CLAUDE_CODE_OAUTH_TOKEN` (subscription token, no API billing),
  `MAIL_USERNAME`, `MAIL_PASSWORD`, `ARTIFICIAL_ANALYSIS_API_KEY`.

## Gotchas
- A pasted OAuth token can carry a newline the CLI rejects; the workflow strips
  whitespace before `claude -p` (c025d88).
- OpenRouter `/models` always reports `discount: 0`; real discounts are per
  provider on `/models/{id}/endpoints`. Retired models are not discounts (fbd2b97).
- The AA coding index is per model and prices are per 1M tokens, never "per task".
- `data/aa-coding.json` may be absent when the AA step failed; the commit step
  adds it conditionally.
- The workflow header still mentions a phone push; ntfy was removed (d4a4f26),
  email is the only delivery channel.

## Related repos
- `gh-workflow-scheduler` — Cloudflare Worker that dispatches `digest.yml`
  (`src/schedules.ts`, cron `0 5 * * *`).
- `flow-doctor` — `ai_digest` check (run on main + `digests/<date>.md` exists),
  `digest_quality` judges the Markdown, and tracks the OAuth token's 1-year expiry.

## Do not
- Do not add a `schedule:` trigger; dispatch comes from the scheduler.
- Do not let the prompt make Claude run git or send notifications; those stay
  workflow steps.
- Do not edit files on the `digests` branch by hand.
