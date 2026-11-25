# team-review changelog

Every change since the skill was first designed, in the order it was made, with the reason for it.
All changes so far were made on 2026-11-17.

## 1. Design and first version

| Decision | Why |
|---|---|
| Run the review **locally**, not on GitHub | Many automated suggestions are not relevant. The team reads the review first and publishes only what matters. |
| Personal skills in `~/.claude/skills/` for the trial; a plugin later | Personal skills work in the CLI, the VS Code and IntelliJ extensions and the desktop app, and are easy to try. A plugin is the way to share and update them once the design settles. |
| Target: nothing (current branch), a branch name, a PR number or a PR URL | These are the ways people refer to the work under review. |
| Diff = `merge-base(base, head)..head` | It is the same diff GitHub shows, so line numbers match the PR. |
| Severity scale 🔴 blocker / 🟠 major / ❓ question / 🟡 minor / 🔵 nit, plus a separate confidence (high / medium / low) | Mixing "how bad" with "how sure" is the main source of noise. Nits and low-confidence findings are hidden by default. |
| Independent roles in parallel: ticket, architecture, ADR, security, correctness, tests | Each role looks from one angle. Independence means that agreement between roles is evidence. Correctness and tests were added to the roles first proposed, because most real defects are found there. |
| A **context builder** before the roles | It gathers the ticket, the ADRs and the team context once, so every role works from the same facts. |
| A **judge** after the roles that verifies, de-duplicates, ranks and assigns IDs | Unverified findings destroy trust in a review tool. The judge is the filter against false positives. |
| Every review starts with "What this PR does" | It was asked for, and it gives the reader orientation before the findings. |
| Local IDs `R1, R2…` and a separate posting skill | Findings can then be published selectively, by ID. |
| Runs stored in `.git/team-review/`, never committed | Reviews are personal working material, not project history. |
| Jira key taken from the branch name | That is the team convention. |
| ADRs in `docs/adrs` by default; optional per-repo `.claude/team-review.md` | That is where the team keeps ADRs. Other repos can override it, set their stack, ignore generated paths and add project rules. |
| Stack from the repo config, the team default or detection | The roles need to know the languages and frameworks. |
| `lang=bg`: reports in English by default, Bulgarian on request | English is the team default; Bulgarian is the team's other language. |
| `--text` in the posting skill **replaces** the generated text | Decided by the team. |
| Team sources listed in `context/team-context.md` (repos and Confluence pages) and condensed into a cached **team brief** | Reviewers need the team's way of working and the system landscape. Fetching Confluence on every review would be slow. |
| `README.md` describing every step and flag | Requested, so colleagues can use the skill without asking. |

## 2. Team sources filled in

- Added the team's own repository and its two Confluence pages (the code review guidelines and the Definition of Ready)
  to `team-context.md`. **Why:** they are the team's own rules for reviews and tickets.
- Checked access: `gh` reads the repo, and the Atlassian connector reads both pages after it was authorised.

## 3. Team conventions from the Confluence pages

- **Comment labels from the team's code review agreement** (`blocking`, `question`, `suggestion`, `nit`) on every posted comment.
  **Why:** the agreement requires every comment to say whether it blocks the merge.
- **Definition of Ready sections** extracted from the ticket (Context, User story, Acceptance criteria, Scope, Edge cases,
  Testing, Technical details, Implementation notes, Developer references, Open questions), and the ticket role checks
  them: edge cases handled, excluded scope untouched, prescribed approach followed, required testing present, open
  questions not silently decided. **Why:** the team's tickets follow this structure, which makes them checkable.

## 4. Code in every finding

- Every finding shows the **current code** (copied exactly from the reviewed commit) and an **example fix** that uses the
  codebase's real names and patterns. The judge re-copies the excerpts and checks the fixes.
  **Why:** the first real review (the first reviewed PR) described problems without showing the code or how to fix it.

## 5. Team label style

- Labels are written `**suggestion**: text`, not `suggestion: text`; a label typed by the user is normalised to that form.
  **Why:** that is how the team writes review comments.

## 6. Fixes from the first review of the skill (points 1–9, 14, 16, 21)

| # | Change | Why |
|---|---|---|
| 1 | Posting after a review with `--uncommitted` sends every finding as a general comment | The line numbers come from uncommitted code that the PR does not have, so inline comments could land on the wrong line. |
| 2 | `latest` points at a run only after its review is complete (atomic swap) | A failed or interrupted review used to hide the previous good one from the posting skill. |
| 3 | Agents are read-only on the repo and never post anything | The general-purpose agent could edit files; nothing stopped it. |
| 4 | Text from the PR, ticket, comments, Confluence and code is data, never instructions; an injection attempt in the diff is a security finding | Agents with `gh` and shell access read text written by others. |
| 5 | Team-brief cache moved to `~/.cache/team-review/`; no `__pycache__` or `.DS_Store` in the skill folders | A plugin update would wipe a cache inside the skill, and the junk files ended up in what is shared. |
| 6, 7 | The existing PR discussion is read. Points already raised by a person, or answered by the author, are rejected with a link. Points posted earlier by team-review are recognised by their tag and not posted twice. | Without it, the review repeated colleagues' comments and could post the same point twice. |
| 8 | The reviewed repo's `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md` and `.claude/rules/*.md` are read | That is where each project writes its conventions. |
| 9 | The ticket role checks three rules of the team's code review agreement: one purpose per PR, a description that says what to verify and where to look, and the draft state (shown in the report header) | These are team rules a reviewer can check. |
| 14 | **Adaptive roles:** a role with nothing to review for this kind of diff (docs only, tests only, config only) is skipped with a reason. `--quick` runs only correctness and security. `--full` turns adaptive skipping off. | Lower cost and time for small or narrow PRs. |
| 16 | Posting falls back to the local git diff when GitHub's diff API refuses a very large PR | Posting used to fail on large PRs. |
| 21 | The README was split into a short usage guide and `docs/how-it-works.md` | The single README had grown to more than 400 lines. |

## 7. Larger team brief

- The team brief went from at most ~900 words to **2,000–3,500 words**. It must keep every checkable rule with its
  identifier (the numbered agreement rules and the Definition of Ready sections), read Confluence pages in full, organise the brief by source, and end with a coverage
  line. **Why:** the first brief was about 250 words, so rules were being lost, and a rule that is not in the brief is a
  rule no role checks.
- The cache is now rebuilt when the context-builder instructions change, not only when the sources change.
  **Why:** otherwise the new limit would have waited up to 7 days to take effect.
- The idea of copying key rules directly into `team-context.md` was recorded in `docs/backlog.md`.

## 8. `/team-review:fix`

- A third command applies the example fixes of chosen findings to the working tree of the reviewed branch, verifies them
  with the project's lint, typecheck and tests, and marks them as fixed, skipped or failed. It never commits or pushes,
  and the posting skill skips fixed findings. **Why:** the team's code review agreement asks the author to run an automated review and fix
  what it finds before asking a person.

## 9. Cost measurement

- The first review (the first reviewed PR) cost about $3.50. To find out why, a second PR (8 files, +217/−47) was reviewed in a
  measured run: about **821k tokens** across 8 general-purpose agents, about 5 minutes.
- Findings: one agent's fixed overhead is about 60–70k tokens before it does any work (the security role used 79k tokens
  with 7 tool calls and found nothing). The overhead comes from the instructions and tool definitions of the
  general-purpose agent, which loads every tool. Four roles found the same major problem independently; the
  architecture and ADR roles overlapped on two findings.

## 10. Lean agents, model config, merged role

| Change | Why |
|---|---|
| **Lean agents:** `team-review:worker` (Read, Grep, Glob, Bash, Write) for every role and the judge; `team-review:context` for the context builder | Agents cannot share loaded tools, because each agent is a separate model call. The way to cut the fixed overhead is to give each agent only the tools it needs. The context builder keeps all tools, because the Atlassian connector's tool names differ between installations. |
| Agent definitions live in `team-review/agents/` and are linked into `~/.claude/agents/` | One source of truth. A plugin carries an `agents/` folder, so they move into the plugin unchanged. |
| Fallback to the general-purpose agent, with a notice, when the agent files are missing | The review still works for a colleague who has not linked them yet. |
| **`config.json`** with a model per agent; **Sonnet everywhere** by default, the judge included | Model choice becomes a team setting, not something hard-coded. Opus can be switched on per agent when needed. |
| **`architecture` and `adr` merged** into one `architecture` role (`adr` remains an alias) | They read the same code from similar angles and produced duplicate findings. One agent less per review. |
| `docs/changelog.md` (this file) | Requested, so the reasons behind each change are not lost. |

## 11. Measuring the lean agents, and the related-code step

- **Review of the second reviewed PR with the lean agents and Sonnet everywhere:** about **328k tokens** against 821k (−60%); the roles
  and the judge alone dropped from about 702k to about 194k (−72%). Security went from about 79k to about 18k tokens for
  the same result, which confirmed that the fixed overhead was the main cost.
- **But it missed the major defect** found by the first review: an event filter in the changed domain still judged a condition by the first listed item, even if it had been removed. The defect is still in the code, in files the PR does
  not touch. Re-running correctness and architecture twice more with the lean agent missed it every time (0 of 7 role
  runs), so it was a pattern, not chance. Likely causes: the lean roles explored less beyond the diff, and the earlier
  context happened to mention that there are two similar checks.
- **Fix: related code.** `collect.py` now searches the repo for the diff's distinctive terms (ticket keys, failure texts,
  declared names) and writes the files outside the diff that contain them to `related_code.json`. The correctness and
  architecture roles must read the related source files that share a term with a changed rule, and must trace where the
  changed code's inputs are produced. **Why:** the same rule is often implemented in more than one place, and a fix in
  one place that misses the other is exactly the kind of defect a reviewer should catch.
- **Result:** with the change, correctness and architecture found the defect in **4 of 4** runs, at about 43–45k tokens
  per role (about 8k more than without it, and less than half of the general-purpose agent's ~105k).
- **Full review with the final setup:** about **284k tokens** (−65% against the first 821k), with the team brief cached. The
  major defect is found with high confidence and verified by the judge, alongside a new question (does a later event always
  place a site that was turned away?). The context builder is now the largest single cost (about 100k, 35% of the total),
  which supports the backlog item on caching the team and repo context.

## 12. One finding, one comment

- **Problem:** on the first reviewed PR the findings were posted together: findings that could not go on a line were combined into the
  body of one GitHub review. The author could not answer and resolve them one by one, and a review body cannot be
  resolved at all.
- **Change (team rule):** every finding is now posted as its **own** comment. It goes on the line when the line is in the
  PR diff, on the file when the file is in the PR but the line cannot be used, and otherwise as a separate comment in
  the PR conversation. Line and file comments are resolvable threads; conversation comments cannot be resolved by
  GitHub, so the author replies. Each finding records the URL of its own comment, saved right after it is posted.

## 13. Context in three cached layers
_2026-11-18._

- **Why:** in the measured review of the second reviewed PR the context builder was the largest single cost (about 100k tokens, 35%),
  and it was the only agent with all tools. Most of what it gathered changes rarely.
- **Change:** the context is split into three layers.
  - **Team** (team brief): built by `roles/team-brief.md` with the all-tools agent, only when stale (7 days, or when
    `team-context.md` or its instructions change).
  - **Repo** (ADR index, repo rules, stack, as on the base branch): built by a lean agent with `roles/repo-context.md`,
    cached per repository in `~/.cache/team-review/repos/`, and keyed by the git hashes of its sources on the base
    branch, so it is rebuilt exactly when an ADR or rule file changes there. `context_cache.py commit-repo` records the
    cache only once the file is complete.
  - **PR** (summary, ticket and its DoR sections, ADRs and rules changed by the PR, PR discussion): built on every review
    by a lean agent with `roles/pr-context.md`. The main session fetches the ticket itself.
  - `context_cache.py assemble` builds `context.md` from the three; the roles are unchanged.
- **New command `/team-review:context`:** shows the status of the cache or rebuilds it (`--team`, `--repo`, `--status`),
  without running a review.
- **Config:** the `context-builder` model entry became `team-brief`, `repo-context` and `pr-context`; an old
  `context-builder` entry still applies to all three.
- **Measured on the third reviewed PR:** rebuilding the team and repo layers cost about $0.73 (team brief $0.60, repo
  context $0.13), and a review with both layers cached skipped it. With the main session and the judge on Opus, a
  review cost $3.87 with the rebuild and $3.16 without it. Details are in
  [measurements.md](measurements.md).

## 14. Measurements in their own document
_2026-11-18._

- **Why:** the measurements were growing inside `how-it-works.md`, which should describe how the skill works rather
  than what each setup cost.
- **Change:** the measurements of the second PR moved from `how-it-works.md` to the new `docs/measurements.md`, which also
  records four reviews of the third PR with their cost per stage and their tokens. `how-it-works.md` and the
  README link to it.
- **What the reviews of the third PR showed:** the main session was the largest single cost. On Opus it cost $1.13–1.27, which
  was 35–45% of a review, and on Sonnet the same work cost $0.67. A Sonnet judge cost about $0.57 less than an Opus
  judge. A review with Sonnet everywhere cost $2.21, against $3.16 with the main session and the judge on Opus. The
  Sonnet judge also found the same major finding as the Opus judge.

## 15. Focus: `--focus` and "Anything to scrutinise?"
_2026-11-18._

- **Why:** the author, or whoever runs the review, often already knows which points need a careful look. The team's PR
  template asks for them in "Anything to scrutinise?" (the team's code review agreement), but the review did not use them, and
  when it found nothing there was no way to tell whether a point had been examined at all.
- **Change:**
  - `--focus "…"` (repeatable) gives focus items: free text, a file, or `file:line` with a question.
  - The bullets of the PR description's "Anything to scrutinise?" section become focus items automatically, so a reviewer
    gets the author's points without typing them. Placeholder text and empty answers are ignored; `--no-pr-focus` turns
    this off. At most 10 items are used.
  - Focus items are listed at the top of `context.md`. Every role examines the items in its area in depth and answers
    each one: a finding, or "checked, no issue" with evidence.
  - The judge checks the answers, examines any item no role covered, and writes `focus_results`. The report shows a
    **Focus areas** table before the findings.
  - Focus adds depth and never narrows the review. Its text is data: it can only add scrutiny. When there is focus, the
    correctness role always runs.
- **Tested:** focus extraction on the real descriptions of two reviewed PRs (3 and 4 points), on the empty template and
  on "None"; the context assembly; and the report section in English and Bulgarian. A full review with focus has not
  been measured yet.


## 16. Packaged as a plugin

- **Change:** the four skills and two agents moved from `~/.claude` into this repository, which is both the plugin and
  its marketplace. Commands are namespaced: `/team-review:review`, `/team-review:post`, `/team-review:fix`,
  `/team-review:context`; the agents are `team-review:worker` and `team-review:context`. **Why:** one install command,
  versions and updates through git, and no path that only works in one person's home folder.
- **Change:** every path now starts at `${CLAUDE_PLUGIN_ROOT}` (called `PLUGIN_ROOT` in the instructions).
  `collect.py --skill-dir` became `--plugin-root`.
- **Change:** nothing team-specific ships in the plugin. The team context (`team-context.md`) is found in
  `<repo>/.claude/team-context.md`, then in `~/.config/team-review/team-context.md`, and `templates/team-context.md`
  is the empty template. Without one, the review runs without a team layer. **Why:** other teams and projects can use
  the plugin with their own sources.
- **Change:** the team-brief cache is per `team-context.md` file (`~/.cache/team-review/team-briefs/<hash>.md`), so two
  teams on one machine do not overwrite each other's brief.
- **Change:** model overrides go in `~/.config/team-review/config.json` and are merged over `config.default.json`, so
  an update never loses a personal setting.
- **Change:** examples no longer name the first team's tickets, files or Confluence pages, and the PR-hygiene step of
  the ticket role says that rules in the team brief take precedence over its defaults.
- `docs/measurements.md` was not carried over (it records reviews of one team's pull requests).
