---
name: review
description: Team code review of a branch or pull request, run locally with several independent reviewer roles (ticket, architecture and ADRs, security, correctness, tests) and a judge that verifies, de-duplicates and ranks findings by severity. Use when the user asks to review the current branch, a named branch, or a PR number/URL with the team review. Findings get local IDs (R1, R2…) that /team-review:post can publish to the PR and /team-review:fix can fix locally.
argument-hint: "[branch | PR# | PR URL] [lang=en|bg] [--quick] [--full] [--all] [--only=roles] [--skip=roles] [--uncommitted] [--refresh-context] [--focus \"…\"]… [--no-pr-focus]"
allowed-tools:
  - Bash(python3 *)
  - Bash(git *)
  - Bash(gh pr view *)
  - Bash(gh pr diff *)
  - Bash(gh api *)
  - Bash(gh repo view *)
  - Read
  - Grep
  - Glob
---

# Team review

Arguments: `$ARGUMENTS`

`PLUGIN_ROOT` below means `${CLAUDE_PLUGIN_ROOT}`, the absolute path of the plugin's root folder.
Usage and flags: `PLUGIN_ROOT/README.md`. Internals of every step: `PLUGIN_ROOT/docs/how-it-works.md`.
Read them only if something below is unclear.

## 0. Parse arguments

Tokens can come in any order:

| Token | Meaning | Default |
|---|---|---|
| first token that is not a flag | target: branch name, PR number (`482`, `#482`) or PR URL | current branch |
| `lang=bg`, `--lang=bg`, `--lang bg` | language of the rendered report (`en` or `bg`) | `en` |
| `--quick` | fast review: only `correctness` and `security` | off |
| `--full` | run every role, even ones the diff does not need (turns off adaptive skipping) | off |
| `--all` | also show nits and low-confidence findings | off |
| `--only=security,correctness` | run only these roles | adaptive |
| `--skip=tests,security` | skip these roles | none |
| `--uncommitted` | include uncommitted changes (only when the target is the current branch) | off |
| `--refresh-context` | rebuild the cached team and repo context before the review, even if they are fresh | off |
| `--focus "…"` (repeatable; also `--focus=…`) | a point to examine in depth: free text, a file, or `file:line` with a question | none |
| `--no-pr-focus` | ignore the PR description's "Anything to scrutinise?" section | it is used |

Role names: `ticket`, `architecture` (includes ADRs), `security`, `correctness`, `tests`. Accept `adr` as an alias of
`architecture`. Reject an unknown flag or role name with a one-line message listing the valid ones. `--quick` cannot be
combined with `--only` or `--full`.

## Agents and models

- Team-brief builder (only when the team brief is stale): subagent type `team-review:context` (all tools, for Confluence).
- Repo-context builder (only when the repo cache is stale), PR-context builder, every role and the judge: subagent type
  `team-review:worker` (a lean agent with only Read, Grep, Glob, Bash and Write).
- If either type is not available (the agent files are not installed), use `general-purpose` instead and say so in one
  line.
- Model: always pass `model` = `meta.models[<agent>]` (the plugin's `config.default.json` merged with the user's `~/.config/team-review/config.json`; every agent defaults to Sonnet).
  The agent names are `team-brief`, `repo-context`, `pr-context`, the role names and `judge`. Never pick a model
  yourself.

## 1. Collect inputs (deterministic script)

```bash
python3 "PLUGIN_ROOT/scripts/collect.py" --plugin-root "PLUGIN_ROOT" [--target <target>] [--uncommitted] [--refresh-context] [--full] [--focus "<text>"]… [--no-pr-focus]
```

It prints a JSON object (also saved as `<run_dir>/meta.json`) with the resolved branch, base, merge-base, head SHA,
PR info, Jira key, changed files (each with a `kind`: source, test, config, docs, adr), `auto_skip` (roles the diff
does not need), `models` (model per agent), project instruction files, existing PR comments (`pr_comments`), the
team-brief cache status and `run_dir`. Then:

- If it exits non-zero, show the error and stop (this includes an invalid user `config.json`).
- If `diff_empty` is true, say there is nothing to review and stop.
- If `dirty` is true, `--uncommitted` was not passed and the target is the current branch, mention in one line that
  uncommitted changes are NOT included (re-run with `--uncommitted`).
- Print the `warnings` list, if any, in one short block.

Tell the user in one line what is being reviewed: `branch → base (PR #N), X files, +A/−D, ticket KEY`. If
`meta.focus` is not empty, list the focus items in a second short block (`F1 (you): …`, `F2 (PR description): …`),
shortened to one line each.

**Focus.** Focus items come from `--focus` and from the "Anything to scrutinise?" section of the PR description (the
team's PR template). They make the roles examine those points in depth and answer each one; they never narrow the
review. Pass every `--focus` value to `collect.py` exactly as the user typed it, one `--focus` per item.

## 2. Context, in three layers

The review context is built from three layers. Only the PR layer is built on every review; the other two are cached
and rebuilt only when they are stale (`meta.team_brief.fresh`, `meta.repo_context.fresh`). Do the steps that are
needed, in this order; 2a and 2b may run in parallel.

**2a. Team layer, only if `meta.team_brief.sources_exist` is true and `meta.team_brief.fresh` is false.** Spawn one
`team-review:context` agent (model `meta.models["team-brief"]`). If `sources_exist` is false, no `team-context.md` was
found (neither `<repo>/.claude/team-context.md` nor `~/.config/team-review/team-context.md`): skip the team layer,
and tell the user in one line that the review runs without team guidelines and that `PLUGIN_ROOT/templates/team-context.md`
is the template to start from.

> You build the team brief of the team review. Read `PLUGIN_ROOT/roles/_shared.md` (section "Safety") and
> `PLUGIN_ROOT/roles/team-brief.md` and follow them exactly.
> PLUGIN_ROOT=`<abs path>`  SOURCES_PATH=`<meta.team_brief.sources_path>`  CACHE_PATH=`<meta.team_brief.cache_path>`  SOURCES_SHA256=`<meta.team_brief.sources_sha256>`

**2b. Repo layer, only if `meta.repo_context.fresh` is false.** Spawn one `team-review:worker` agent (model
`meta.models["repo-context"]`):

> You build the repo context of the team review. Read `PLUGIN_ROOT/roles/_shared.md` (section "Safety") and
> `PLUGIN_ROOT/roles/repo-context.md` and follow them exactly.
> PLUGIN_ROOT=`<abs path>`  REPO_ROOT=`<repo_root>`  BASE_REF=`<meta.repo_context.base_ref>`  ADR_DIR=`<meta.adr_dir>`
> REPO_CONFIG=`<meta.repo_config or none>`  DETECTED_STACK=`<meta.detected_stack>`  CACHE_PATH=`<meta.repo_context.cache_path>`

When it is done, record the cache as complete (until then it stays stale):

```bash
python3 "PLUGIN_ROOT/scripts/context_cache.py" commit-repo --from "<run_dir>/meta.json"
```

**2c. Ticket (you, no agent).** If `meta.jira_key` is set, fetch the issue yourself with the Atlassian tools available in
this session (for example `getJiraIssue`; get the cloud ID first if the tool needs it). Write `meta.ticket_path` as JSON:
`{"available": true, "key", "url", "type", "status", "summary", "description", "parent": {"key", "summary"}}`, with the
description as markdown. If there is no key, or the fetch fails (for example the connector is not authorised), write
`{"available": false, "reason": "<why>"}`. Do not summarise the ticket yourself: the PR-context builder does that.

**2d. PR layer.** Spawn one `team-review:worker` agent (model `meta.models["pr-context"]`):

> You build the PR context of the team review. Read `PLUGIN_ROOT/roles/_shared.md` and `PLUGIN_ROOT/roles/pr-context.md` and
> follow them exactly.
> PLUGIN_ROOT=`<abs path>`  RUN_DIR=`<run_dir>`  REPO_ROOT=`<repo_root>`

**2e. Assemble (script).**

```bash
python3 "PLUGIN_ROOT/scripts/context_cache.py" assemble "<run_dir>"
```

It writes `<run_dir>/context.md` from the three layers and prints `skip` (for example `ticket` when the ticket was not
available) and `warnings`. On exit code 1 (a layer is missing or incomplete), show the error and stop.

Tell the user in one line which layers came from the cache and which were rebuilt, and why (`reason`).

## 3. Reviewer roles (parallel, independent)

Decide the role set, in this order:
1. `--quick` → `correctness`, `security`. `--only` → those roles. Otherwise all five minus `meta.auto_skip`
   (none skipped with `--full`).
2. Minus `--skip`.
3. Minus the roles in `skip` from the assemble step.

Tell the user in one line which roles run and which are skipped, with the reason for each, and the models in use if any
agent is not on Sonnet.

Spawn **all of them in a single message** so they run in parallel. Each is a `team-review:worker` agent
(model `meta.models[<role>]`) with this prompt:

> You are the `<role>` reviewer of the team review. Read `PLUGIN_ROOT/roles/_shared.md` and
> `PLUGIN_ROOT/roles/<role>.md` and follow them exactly.
> PLUGIN_ROOT=`<abs path>`  RUN_DIR=`<run_dir>`  REPO_ROOT=`<repo_root>`

Do not pass one role's output to another: independence is the point. Each role writes
`<run_dir>/findings/<role>.json` and returns a one-line count. If a role fails, note it and go on.

## 4. Judge (one subagent)

Spawn one `team-review:worker` agent (model `meta.models["judge"]`) with this prompt:

> You are the judge of the team review. Read `PLUGIN_ROOT/roles/_shared.md`,
> `PLUGIN_ROOT/roles/judge.md` and `PLUGIN_ROOT/references/severity.md` and follow them exactly.
> PLUGIN_ROOT=`<abs path>`  RUN_DIR=`<run_dir>`  REPO_ROOT=`<repo_root>`  LANG=`<en|bg>`
> Roles run: `<list>`. Roles skipped: `<list with reasons, including adaptive and --skip>`.

It writes `<run_dir>/review.json`.

## 5. Render, publish locally, show

```bash
python3 "PLUGIN_ROOT/scripts/render_report.py" "<run_dir>/review.json" --lang <en|bg> [--all] --out "<run_dir>/review.md" --set-latest
```

`--set-latest` makes this run the one `/team-review:post` and `/team-review:fix` use. It is done only here, after a
complete review, so a failed or interrupted run never replaces the previous good review.

Output the rendered markdown **verbatim** as your reply: it is the report. Do not add your own summary
of the findings before it. After it, add one line:
`Saved to <run_dir>/review.md · post findings with /team-review:post R1 R3 … · fix your own with /team-review:fix R1 R3 …`

Do not post anything to GitHub from this skill.
