---
name: context
description: Show or rebuild the cached context of /team-review:review for the current repository - the team brief (Confluence and team repositories) and the repo context (ADR index, repo rules and stack on the base branch). Use when the user asks to refresh, rebuild or check the team-review context or cache, for example after a Confluence page, an ADR or CLAUDE.md changed.
argument-hint: "[--team] [--repo] [--status]"
disable-model-invocation: true
allowed-tools:
  - Bash(python3 *)
  - Bash(git *)
  - Bash(gh repo view *)
  - Bash(gh api *)
  - Read
  - Grep
  - Glob
---

# Rebuild the team-review context cache

Arguments: `$ARGUMENTS`

`PLUGIN_ROOT` below means `${CLAUDE_PLUGIN_ROOT}`, the root of the plugin. Documentation: `PLUGIN_ROOT/README.md` (section "Context
cache") and `PLUGIN_ROOT/docs/how-it-works.md`.

## 0. Parse arguments

| Token | Meaning |
|---|---|
| (none) | rebuild only the layers that are stale or missing |
| `--team` | rebuild the team brief now, even if it is fresh |
| `--repo` | rebuild the repo context of this repository now, even if it is fresh |
| `--status` | only show the status of both layers; rebuild nothing |

`--team` and `--repo` can be combined.

## 1. Status

```bash
mkdir -p ~/.cache/team-review && python3 "PLUGIN_ROOT/scripts/collect.py" --plugin-root "PLUGIN_ROOT" --context-only [--refresh-team] [--refresh-repo] > ~/.cache/team-review/status.json
```

Pass `--refresh-team` for `--team` and `--refresh-repo` for `--repo`. Step 3 needs the saved status file. On exit code
1, show the error (it goes to stderr) and stop; otherwise read the status from `~/.cache/team-review/status.json`.

Show a two-line status: team brief (fresh or the `reason`, and its path) and repo context (fresh or the `reason`, the
base ref, and its path). With `--status`, stop here.

## 2. Rebuild what is needed

Use the models from `models` in the status (`team-brief`, `repo-context`). Run the two in parallel when both are needed.

- **Team brief** (`team_brief.sources_exist` is true and `team_brief.fresh` is false; if no `team-context.md` exists, say so and point to `PLUGIN_ROOT/templates/team-context.md`): spawn one `team-review:context` agent with the prompt from step 2a of
  `PLUGIN_ROOT/skills/review/SKILL.md`, using `team_brief.sources_path`, `team_brief.cache_path` and `team_brief.sources_sha256` from the status.
- **Repo context** (`repo_context.fresh` is false): spawn one `team-review:worker` agent with the prompt from step 2b of
  `PLUGIN_ROOT/skills/review/SKILL.md`, using `repo_root`, `repo_context.base_ref`, `adr_dir`, `repo_config`, `detected_stack` and
  `repo_context.cache_path` from the status.

If an agent type is not available, use `general-purpose` and say so.

## 3. Record and report

After a repo-context rebuild, record it as complete:

```bash
python3 "PLUGIN_ROOT/scripts/context_cache.py" commit-repo --from ~/.cache/team-review/status.json
```

Report what was rebuilt, the word count of each layer, and any unavailable sources the team-brief builder listed.
