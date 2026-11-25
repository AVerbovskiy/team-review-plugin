---
name: fix
description: Apply fixes for selected findings of the latest local /team-review:review run to the working tree of the reviewed branch, then verify them with the project's own lint, typecheck and tests. For the author's self-review before asking for human review. Only when the user explicitly asks to fix review findings by ID (R1, R2…) or keyword (blockers, majors, all).
argument-hint: "<R1 R3 … | blockers | majors | all> [--dry-run] [--no-verify] [--force] [--branch name]"
disable-model-invocation: true
allowed-tools:
  - Bash(python3 *)
  - Bash(git status *)
  - Bash(git diff *)
  - Bash(git rev-parse *)
  - Read
  - Grep
  - Glob
  - Edit
  - Write
---

# Fix team-review findings locally

Arguments: `$ARGUMENTS`

`FIX` below means `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/fix_review.py"`.
Documentation: `${CLAUDE_PLUGIN_ROOT}/README.md` and `${CLAUDE_PLUGIN_ROOT}/docs/how-it-works.md`.

This implements the author's self-review: mechanical problems are fixed
before a person spends time on the PR. It does **not** replace human review. Never present the result as proof that the
change is correct.

## 0. Parse arguments

| Token | Meaning | Default |
|---|---|---|
| `R1 R3 …` | finding IDs from the latest review of the branch (case-insensitive) | required (or a keyword) |
| `blockers` / `majors` / `all` | all blockers / blockers and majors / every finding | — |
| `--dry-run` | show the plan (what would change where) and stop | off |
| `--no-verify` | do not run lint, typecheck or tests afterwards | verify |
| `--force` | redo findings already marked as fixed | skip them |
| `--branch name` | use the latest review of another branch (you must be on that branch) | current branch |

If no ID or keyword is given, stop and say how to use the command.

## 1. Select

Run `FIX select <selectors> [--force] [--branch name]`. On exit code 1, show the error and stop. The most common one is
being on a different branch than the reviewed one.

From the JSON:
- `skipped`: say in one line which IDs were skipped and why.
- Findings with `fixable: false` (questions, PR-level points with no code fix): list them in one line with
  `why_not_fixable` and leave them out.
- If `uncommitted_files` overlaps the files you will touch, say so in one line. The fixes will mix with those
  uncommitted changes in the same files.

## 2. Plan

For each fixable finding, decide the concrete edit:
- Find the code with `excerpts[].found_at`, which gives where the reviewed code is now. If the file is
  "changed since the review" and the excerpt is not found, read the file and locate the code by meaning. If it no
  longer exists or the problem is already gone, mark the finding `skipped` with the reason.
- Start from `fix_example` (or `suggestion_code`). It is an **example**: adapt it to the code as it is now, keep the
  surrounding style, and change only what the finding needs. Do not refactor beyond the finding, rename unrelated
  things, or reformat files.
- For a test finding, add the test case next to the closest existing test, in the same style.
- If two findings touch the same code, apply them together and consistently.
- If a finding is ambiguous or the fix needs a design decision (an API change, a migration, a new dependency, a
  change to a public contract), do not guess. Leave it out and say why.

Show the plan as a short table: ID → files → what will change (one line). With `--dry-run`, stop here.

## 3. Apply

Make the edits with the Edit tool (Write only for a new file). Touch only the files in the plan.
Never commit, push, stash, reset, switch branches, or install packages.

## 4. Verify (unless `--no-verify`)

Use the project's own tooling, from `checks` in the JSON and the repo's `CLAUDE.md`. Prefer targeted runs on the changed
files over full runs, for example with pnpm: `pnpm exec eslint <files>`, `pnpm exec tsc --noEmit -p tsconfig.json`,
`pnpm exec vitest run <changed or related test files>`.
- Ask before running anything that needs infrastructure (Postgres, Docker, Kafka: e2e and acceptance suites), or that
  takes more than a few minutes. Otherwise skip it and say it was not run.
- If a check fails because of a fix, correct the fix (at most two attempts per finding). If it still fails, revert that
  finding's edits and mark it `failed` with the error in one line.
- If a check fails for reasons unrelated to the fixes (it already failed before), say so and do not try to fix it.

## 5. Record and report

Run `FIX mark <ids> --status fixed --files <comma-separated files>` for the fixed findings, and the same with
`--status skipped` or `--status failed` and `--note "<reason>"` for the others. `/team-review:post` will not post findings
marked as fixed (unless forced), and the report shows them with 🛠️.

Then reply with:
- a table: ID | status (🛠️ fixed / ⏭️ skipped / ❌ failed) | files | note
- which checks ran and their result, and which were not run
- `git diff --stat`
- one line: the changes are in your working tree, not committed. Review them with `git diff`, then commit.
