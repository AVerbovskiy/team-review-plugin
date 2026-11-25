---
name: post
description: Publish selected findings from the latest local /team-review:review run to the GitHub PR, each finding as its own comment (on the line where possible). Only when the user explicitly asks to post review findings by ID (R1, R2…) or by keyword (blockers, majors, questions).
argument-hint: "<R1 R3 … | blockers | majors | questions> [--text \"…\"] [--general] [--suggestion] [lang=en|bg] [--branch name] [--pr N] [--force] [--dry-run]"
disable-model-invocation: true
allowed-tools: Bash(python3 *) Bash(git rev-parse *) Bash(gh pr view *) Bash(gh pr diff *) Read
---

# Post team-review findings to the PR

Arguments: `$ARGUMENTS`

`POST` below means `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/post_review.py"`.
Usage: `${CLAUDE_PLUGIN_ROOT}/README.md`; posting internals: `${CLAUDE_PLUGIN_ROOT}/docs/how-it-works.md`.

## 0. Parse arguments

| Token | Meaning | Default |
|---|---|---|
| `R1 R3 …` | finding IDs from the latest review of the branch (case-insensitive) | required (or a keyword) |
| `blockers` / `majors` / `questions` | all blockers / blockers + majors / all questions | — |
| `--text "…"` | **replaces** the generated comment text (only with exactly one ID); the team prefix is still added; a label the user already typed is normalised to `**label**:` | generated text |
| `--general` | post as a separate comment in the PR conversation instead of on the line | on the line when possible |
| `--suggestion` | add a GitHub ```suggestion``` block when the finding has replacement code | off |
| `lang=bg` / `--lang bg` | language of the posted text | `en` |
| `--branch name` | use the latest review of another branch | current branch |
| `--pr N` | post to this PR instead of the one recorded in the review | from review |
| `--force` | post again findings that were already posted | skip them |
| `--dry-run` | show what would be posted and stop | off |

If no ID or keyword is given, stop and say how to use the command.

Each finding is posted as its own comment (one finding = one comment). Every comment starts with a severity prefix, so the author sees what blocks the merge:
`**blocking**:` (blocker, major), `**question**:`, `**suggestion**:` (minor), `**nit**:`: the label in bold,
then the colon. The script adds it and normalises a label the user typed, so do not add it yourself.

## 1. Preview (always)

Run `POST <selectors> [flags] --dry-run`.

- Exit code 1: show the error and stop.
- Exit code 3 (translation missing for the requested `lang`): open the review file
  (`<git-common-dir>/team-review/<branch>/latest/review.json`). For each listed ID, add
  `i18n.<lang>` with `title`, `problem`, `why`, `suggestion`, translated naturally. Keep code, identifiers
  and the usual English technical terms. Save it and run the preview again.

Show the user a compact preview from the JSON result:
- target PR and whether the review is **stale** (`stale: true` means the PR has new commits since the review)
- per finding (`plan`): ID, where it goes (`line` at `file:line`, `file`, or `pr` conversation, with `reason`) and
  whether the author can resolve it (`resolvable`)
- if `includes_uncommitted` is true: that the review included uncommitted changes, so no finding goes on a line
- the exact text of each comment (`comments[].body`)
- IDs skipped because they were already posted or already fixed locally with `/team-review:fix`

If `--dry-run` was passed, stop here.

## 2. Confirm, then post

Ask the user to confirm with the question tool (Post / Cancel). The comment is public, so never post
without a clear yes in this turn.

**Team rule: one finding = one comment.** Never combine findings into one comment, and never post them yourself in
another way: the script posts each finding as its own comment.

On yes, run the same command without `--dry-run`. Report the URL of each comment from `posted`, and any `failed`
findings with their error (they can be posted again).
The script marks the findings as posted in review.json, so they are not posted twice and show 📤 when that
review is rendered again. A new `/team-review:review` run starts a fresh review with new IDs.
