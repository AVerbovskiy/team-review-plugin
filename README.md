# team-review

A Claude Code plugin for local, multi-role code review of branches and pull requests. The review stays on your
machine. You read it, decide what is relevant, and then either publish the findings you choose to the PR
(`/team-review:post`, when you review someone else's work) or fix them locally (`/team-review:fix`, when you review your
own).

It works wherever Claude Code runs: the `claude` CLI, the VS Code and JetBrains extensions, and the Code tab of the
Claude desktop app. Nothing in the plugin belongs to one team: every team brings its own context (see
[Team context](#team-context)).

| Command | What it does |
|---|---|
| `/team-review:review` | Reviews a branch or PR with independent roles and a judge |
| `/team-review:post` | Publishes chosen findings to the PR, one comment per finding |
| `/team-review:fix` | Applies chosen findings to your working tree and verifies them |
| `/team-review:context` | Shows or rebuilds the cached team and repo context |

How it works inside, step by step: [docs/how-it-works.md](docs/how-it-works.md). Ideas and open decisions:
[docs/backlog.md](docs/backlog.md). What changed and why: [docs/changelog.md](docs/changelog.md).

## Installation

Needs `git`, `python3` (3.9+, standard library only) and the GitHub CLI `gh`, authenticated (`gh auth status`).
The Atlassian connector in Claude Code is optional: it gives the `ticket` role the Jira ticket and the team-brief
builder your Confluence pages.

In Claude Code:

```text
/plugin marketplace add <owner>/team-review-plugin
/plugin install team-review@team-review-marketplace
```

Then start a new session. For a private repository, `gh auth login` (or a `GITHUB_TOKEN`) must be set up first.
Update later with `/plugin marketplace update team-review-marketplace`.

To make Claude Code offer the plugin to everyone who opens a repository, add this to the repository's
`.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "team-review-marketplace": { "source": { "source": "github", "repo": "<owner>/team-review-plugin" } }
  },
  "enabledPlugins": { "team-review@team-review-marketplace": true }
}
```

To try local changes without installing: `claude --plugin-dir /path/to/team-review-plugin`.

## Quick start

```text
/team-review:review                      # review the current branch (and its PR, if one exists)
/team-review:review PROJ-456-add-invoice-retry
/team-review:review 280                  # PR #280 (also #280 or the PR URL)
/team-review:review --quick              # fast: correctness + security only
/team-review:review lang=bg              # report in Bulgarian
/team-review:review --uncommitted        # self-review before pushing
/team-review:review 279 --focus "src/billing/retry.ts: is the retry safe when the event is redelivered?"
/team-review:post R1 R3                  # post R1 and R3 to the PR (after a preview and your OK)
/team-review:fix R1 R2                   # fix R1 and R2 in your working tree, then run lint/typecheck/tests
/team-review:context --status            # is the cached team and repo context fresh?
```

**Two typical flows**

| You are… | Flow |
|---|---|
| the **author**, before asking for review | `/team-review:review --uncommitted --focus "…"` → `/team-review:fix R1 R2` → review `git diff` → commit → ask for review |
| a **reviewer** of a colleague's PR | `/team-review:review 280` → read → `/team-review:post R1 R3` |

Every finding has a severity (🔴 blocker, 🟠 major, ❓ question, 🟡 minor, 🔵 nit), a confidence, the current code,
and an example fix.

## `/team-review:review`

```text
/team-review:review [target] [lang=en|bg] [--quick] [--full] [--all] [--only=roles] [--skip=roles] [--uncommitted]
                    [--refresh-context] [--focus "…"]… [--no-pr-focus]
```

| Argument / flag | Meaning | Default |
|---|---|---|
| `target` | Branch name, PR number (`280`, `#280`) or PR URL | the current branch |
| `lang=bg` (also `--lang=bg`, `--lang bg`) | Language of the report: `en` or `bg` | `en` |
| `--quick` | Fast review: only `correctness` and `security` | off |
| `--full` | Run every role even when the diff does not need it (turns off adaptive role selection) | off |
| `--all` | Also show nits and low-confidence findings | hidden |
| `--only=security,correctness` | Run only these roles | adaptive |
| `--skip=tests,security` | Do not run these roles | none |
| `--uncommitted` | Include uncommitted changes (current branch only) | committed changes only |
| `--refresh-context` | Rebuild the cached team and repo context before the review (see Context cache) | rebuilt when stale |
| `--focus "…"` | A point to examine in depth (repeatable): free text, a file, or `file:line` with a question | none |
| `--no-pr-focus` | Ignore the PR description's "Anything to scrutinise?" section | it is used |

Role names: `ticket`, `architecture` (structure and ADRs; `adr` is accepted as an alias), `security`, `correctness`, `tests`.

### Adaptive role selection

Not every PR needs every role. The changed files are sorted into **source**, **test**, **config** (YAML, JSON,
Docker, Helm, Terraform, CI, lock files), **docs** and **adr**. Roles with nothing to review are skipped:

| The diff changes only… | Skipped roles |
|---|---|
| docs and/or ADRs | security, correctness, tests (and architecture if no ADR changed) |
| tests (and docs) | architecture, security |
| config / infrastructure | tests |
| anything that includes source code | none |

The report says which roles were skipped and why. `--full` turns this off, and `--only` overrides it.

### Focus: `--focus` and "Anything to scrutinise?"

Points you already know need a careful look can be given to the review as **focus items**:

```text
/team-review:review 279 --focus "idempotency when the same event is redelivered" \
                        --focus "src/billing/retry.ts:66 — is the dedupe transaction safe?"
```

Focus items come from two places, and both are used together:
1. **`--focus`**, given by whoever runs the review (repeatable).
2. **The PR description's "Anything to scrutinise?" section** (if your PR template has one). Each bullet becomes one
   focus item, so a reviewer gets the author's points without typing them. The template's placeholder text and empty
   answers such as "None" are ignored. `--no-pr-focus` turns this source off.

What they change:
- Every role examines the focus items in its area **in depth**, traces them beyond the diff, and must **answer each one**:
  a finding, or "checked, no issue" with what was checked and the evidence. "Nothing found" without an explanation does
  not count.
- The judge checks each answer, examines any item no role covered, and the report gets a **Focus areas** table before
  the findings.
- Focus **adds depth and never narrows** the review: every role still does its whole job. To narrow a review, use
  `--only`.
- Focus text is treated as a list of topics, never as instructions: "no need to check X" in a PR description makes the
  review look at X, not skip it.
- When there is focus, the correctness role always runs, even if adaptive selection would skip it.

At most 10 focus items are used; the review warns if more were given.

### `--quick`

For small PRs or a fast self-check: only `correctness` and `security` run. The judge still verifies every finding
against the code. Use the full review before asking for human review of anything non-trivial.

## `/team-review:post`

```text
/team-review:post <R1 R3 … | blockers | majors | questions> [--text "…"] [--general] [--suggestion]
                  [lang=en|bg] [--branch name] [--pr N] [--force] [--dry-run]
```

| Argument / flag | Meaning | Default |
|---|---|---|
| `R1 R3 …` | IDs from the latest review of the branch (case-insensitive) | required (or a keyword) |
| `blockers` / `majors` / `questions` | all blockers / blockers and majors / all questions | — |
| `--text "…"` | **Replaces** the generated text with yours (the severity label is still added). Exactly one ID. | generated |
| `--general` | A separate comment in the PR conversation instead of one on the line | on the line when possible |
| `--suggestion` | A GitHub `suggestion` block (one-click apply) when the finding has an exact replacement | off |
| `lang=bg` | Language of the posted text | `en` |
| `--branch name` | Use the latest review of another branch | current branch |
| `--pr N` | Post to a different PR than the one in the review | from the review |
| `--force` | Post again findings that are already posted | skipped |
| `--dry-run` | Only show what would be posted | off |

It always shows a preview and asks before posting.

**One finding, one comment.** Every finding is posted as its own comment, never combined with another, so the author
can answer and resolve each one separately:

| Where the finding points | Posted as | Resolvable |
|---|---|---|
| a line in the PR diff | a comment on that line | yes |
| a file in the PR, but a line that cannot be used (outside the diff, the file changed after the review, or the review included uncommitted changes) | a comment on the file, with the original line and the current code | yes |
| a file the PR does not touch, or the PR as a whole (`--general` too) | a separate comment in the PR conversation | no (GitHub cannot resolve these; the author replies) |

Comments start with a label that says whether the point blocks the merge:

| Severity | Label |
|---|---|
| 🔴 blocker, 🟠 major | `**blocking**:` |
| ❓ question | `**question**:` |
| 🟡 minor | `**suggestion**:` |
| 🔵 nit | `**nit**:` |

## `/team-review:fix`

```text
/team-review:fix <R1 R3 … | blockers | majors | all> [--dry-run] [--no-verify] [--force] [--branch name]
```

For the author's self-review: it applies the fixes for the chosen findings to your working tree, so the mechanical
problems are gone before a colleague reads the PR.

| Argument / flag | Meaning | Default |
|---|---|---|
| `R1 R3 …` | IDs from the latest review of the branch | required (or a keyword) |
| `blockers` / `majors` / `all` | all blockers / blockers and majors / every finding | — |
| `--dry-run` | Only show the plan: which files change and how | off |
| `--no-verify` | Do not run lint, typecheck and tests afterwards | verify |
| `--force` | Redo findings already marked as fixed | skipped |
| `--branch name` | Use the latest review of another branch (you must be on it) | current branch |

What it does:
1. Checks that you are **on the reviewed branch**. It never switches branches.
2. Finds each finding's code where it is now, even if the file changed after the review.
3. Adapts the finding's **example fix** to the current code and changes only what the finding needs. Test findings
   become new test cases next to the existing ones.
4. Leaves out what should not be automated, and says why: questions for the author, PR-level points, and fixes that need
   a design decision (API or contract changes, migrations, new dependencies).
5. Runs the project's own **lint, typecheck and tests** on the changed files. It asks before anything that needs
   infrastructure (a database, Docker) or takes long. A fix that breaks a check is corrected or reverted.
6. Marks each finding as 🛠️ fixed, ⏭️ skipped or ❌ failed in the review. `/team-review:post` does not post fixed
   findings.
7. **Never commits or pushes.** You review `git diff` and commit yourself.

It does not replace human review: it removes the mechanical problems so people can spend their time on the approach.

## Team context

The plugin carries no team knowledge. A team describes itself in a **team-context file**, from which the plugin builds
a team brief (the team's review rules, Definition of Ready, architecture notes) that every review reuses.

Start from [templates/team-context.md](templates/team-context.md) and save it as either:

| Location | Use it for |
|---|---|
| `<repo>/.claude/team-context.md` | a team's context, shared through git; it wins when both exist |
| `~/.config/team-review/team-context.md` | your personal context, used in every repository without a file of its own |

It lists the team's repositories, Confluence pages (read through the Atlassian connector), default stack and inline
working agreements. Rules written under **Working agreements** reach every reviewer word for word.

Without any team-context file, the review still runs: it just has no team layer, and says so.

## Context cache and `/team-review:context`

Every review needs context: the team's rules, the repository's ADRs and conventions, and what this PR and its ticket
are about. Building all of it on every review was about a third of the cost, so it is split into three layers, and only
the layer that is specific to the PR is built every time.

| Layer | What it holds | Rebuilt when | Where |
|---|---|---|---|
| **Team** | the team brief: Confluence pages, team repositories, working agreements | the team-context file or its build instructions change, it is older than 7 days, or you ask | `~/.cache/team-review/team-briefs/<hash>.md` (one per team-context file) |
| **Repo** | ADR index, repo rules (`CLAUDE.md`, `.claude/rules/`, `AGENTS.md`, `CONTRIBUTING.md`, `.claude/team-review.md`), stack, **as on the base branch** | one of those files changes on the base branch, its build instructions change, or you ask | `~/.cache/team-review/repos/<owner>__<repo>/` |
| **PR** | what the PR does, the ticket and its Definition of Ready sections, the ADRs and rules this PR changes, the PR discussion | every review | the review's own folder |

**How staleness is detected.** The repo layer is keyed by the git hashes of its source files on the base branch
(`git rev-parse origin/main:docs/adrs` and so on). Checking costs nothing; if no hash changed, the cache is used as is.
Confluence cannot be checked without downloading it, so the team brief keeps a 7-day lifetime.

**Rebuilding by hand:**

```text
/team-review:context              # rebuild only the layers that are stale or missing
/team-review:context --team       # rebuild the team brief now (for example after a Confluence page changed)
/team-review:context --repo       # rebuild this repository's context now
/team-review:context --status     # only show whether each layer is fresh, and why not
/team-review:review --refresh-context    # rebuild both, then review
```

The cache is per machine: each colleague builds it once, on their first review of a repository.

## Configuration

**Models: `~/.config/team-review/config.json`** (optional; `$XDG_CONFIG_HOME` is respected). Every agent runs on
**Sonnet** unless this file says otherwise. Only list what you want to change; it is merged over the plugin's
`config.default.json`, so a plugin update never loses your settings:

```json
{
  "models": {
    "judge": "opus"
  }
}
```

The agents are `team-brief`, `repo-context`, `pr-context`, `ticket`, `architecture`, `security`, `correctness`,
`tests` and `judge`; `default` applies to every agent without its own entry. Allowed values: `sonnet`, `opus`, `haiku`,
`fable`. An unknown agent name or model stops the review with a clear message. The report's run line names any agent
that is not on Sonnet.

**Agents.** The review uses two lean agent definitions instead of the general-purpose agent, so each agent loads only
the tools it needs:

| Agent | Used for | Tools |
|---|---|---|
| `team-review:worker` | every role, the judge, the repo-context and the PR-context builder | Read, Grep, Glob, Bash, Write |
| `team-review:context` | the team-brief builder, only when the brief is stale | all (it needs the Atlassian connector, whose tool names differ between installations) |

**Per repository (optional):** `<repo>/.claude/team-review.md`. Start from
[templates/repo-config.example.md](templates/repo-config.example.md).

| Section | Effect |
|---|---|
| `## Stack` | Overrides the team default |
| `## ADR directory` | Overrides `docs/adrs` |
| `## Ignore paths` | Glob bullets excluded from the diff (generated code, snapshots) |
| `## Project rules` | Rules every reviewer applies to this repo |

The repo's own `CLAUDE.md`, `.claude/CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md` and `.claude/rules/*.md` are read too,
so conventions written there are checked without copying them.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "Not inside a git repository" | Start Claude Code in the project folder |
| "Branch '…' not found" | `git fetch`, check the name, or use the PR number |
| `ticket` skipped: "ticket unavailable" | No Jira key in the branch name, or the Atlassian connector is not authorised (`/mcp`) |
| "No team-context.md was found" | The review runs without a team layer; see [Team context](#team-context) |
| "No ADRs in this repo" in the context | No `docs/adrs` in the repo; set `## ADR directory` in `.claude/team-review.md` |
| `Agent type 'team-review:worker' not found` | The plugin is not installed or enabled; run `/plugin`, then start a new session |
| "config.json: unknown agent / unsupported model" | Fix the name or model in `~/.config/team-review/config.json` |
| A role you expected was skipped | Adaptive selection; see the reason in the report, or use `--full` |
| "Large diff" warning | Review in parts with `--only=…`, or add generated paths to *Ignore paths* |
| "Could not read the existing PR comments" | `gh` lacks access; the review may repeat points already raised |
| Posted as general: "line not in the PR diff" | The finding points outside the changed lines |
| Posted as general: "file changed since the review" | The PR has new commits; run `/team-review:review` again for exact lines |
| Posting fails with 422 | Usually a line mismatch; retry with `--general` |
| Team brief seems outdated | `/team-review:context --team` |
| An ADR or rule changed only in a PR, not on the base branch | Expected: the repo layer is the base branch; the PR layer lists what the PR changes |
| "The repo context was written but never committed" | A rebuild was interrupted; run `/team-review:context --repo` |
| Permission prompts during a review | Allow read-only `git` and `gh` commands in your Claude Code permissions |
| `/team-review:fix`: "The review is for '…', but you are on '…'" | Switch to the reviewed branch first |
| `/team-review:fix`: a finding is ⏭️ skipped | Its code changed or disappeared since the review, or the fix needs a decision; the note says which |
