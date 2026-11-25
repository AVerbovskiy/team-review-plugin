# How team-review works

Usage and flags are in the [README](../README.md). This document explains what happens inside a review and when posting.

## Pipeline

```text
 collect.py ──► context, 3 layers ──────► ┌ ticket ───────┐
 (git, gh,      [team brief]  cached     │ architecture  │
  config.json,  [repo context] cached    │  + ADRs       ├──► judge ──► render_report.py ──► report
  cache keys)   ticket (main session)    │ security      │   (verify,    (markdown, en/bg,
                PR context   per review  │ correctness   │    dedupe,     sets "latest")
                assemble → context.md    └ tests ────────┘    rank, IDs)
                                          only the roles
                [ ] = only when stale     the diff needs,
                                          in parallel
```

### 1. Collect: `scripts/collect.py`
Deterministic, no AI. It:
- resolves the target, base branch, merge-base and head commit
  - **no target:** the current branch. The base is the PR's base, or the default branch when there is no PR.
  - **branch name:** the local branch, otherwise `origin/<branch>`. It is not checked out; reviewers read it from git.
  - **PR number or URL:** the local branch if you have it (with a warning if it differs from the PR head), otherwise
    the PR head is fetched (this also works for forks).
- produces the same diff GitHub shows: `merge-base(base, head)..head`, with 10 lines of context, without *Ignore paths*
- reads PR metadata with `gh`, and the **existing PR discussion** (inline comments, general comments, review
  summaries) into `pr_comments.json`
- takes the **Jira key from the branch name** (`PROJ-456-add-invoice-retry` → `PROJ-456`)
- sorts each changed file into source / test / config / docs / adr and computes the **adaptive role skips**
- collects the **focus items**: the `--focus` values, then the bullets of the PR description's "Anything to scrutinise?"
  section (placeholder text and empty answers dropped; at most 10). They get IDs `F1, F2, …` and go into `meta.focus`.
  When there is focus, the correctness role is never skipped by adaptive selection
- finds **related code**: it takes the distinctive terms on the changed lines (ticket keys such as `PROJ-123`, string
  literals such as failure reasons, declared and compound names), searches the whole repo for them with `git grep`, and
  writes the files **outside the diff** that contain them, with the matching lines, to `related_code.json`. These are the
  likeliest places where the same rule is implemented a second time, or where the changed code's inputs are produced.
  Terms found in more than 12 files are dropped as too common; at most 25 files are listed
- lists the repo's project instruction files (`CLAUDE.md`, `AGENTS.md`, `.claude/rules/*.md` …)
- checks the ADR directory, detects the stack, checks the team-brief cache
- reads `config.default.json` and the user's `~/.config/team-review/config.json` and resolves the model of every agent (Sonnet unless configured otherwise)
- creates the run folder with `meta.json` and `diff.patch`

### 2. Context, in three layers

The shared context every reviewer reads, `context.md`, is assembled from three layers. Only the PR layer is built on
every review; the team and repo layers are cached and rebuilt only when stale.

| Layer | Built by | Holds | Cached in | Stale when |
|---|---|---|---|---|
| Team | `team-review:context` agent (all tools, for Confluence), `roles/team-brief.md` | the team brief: 2,000–3,500 words that keep every checkable rule with its identifier (A1–A12, DoR sections), organised by source, ending with a coverage line | `~/.cache/team-review/team-brief.md`, with a header holding the sources hash and the build date | `team-context.md` or `roles/team-brief.md` changes, it is older than 7 days, or a refresh is asked |
| Repo | lean `team-review:worker`, `roles/repo-context.md` | stack, ADR index (title, status, decision), repo rules from `CLAUDE.md`, `.claude/CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, `.claude/rules/*.md` and `.claude/team-review.md`, **as on the base branch** | `~/.cache/team-review/repos/<owner>__<repo>/repo-context.md` + `manifest.json` | the git hash of any of those sources on the base branch changes, `roles/repo-context.md` changes, or a refresh is asked |
| PR | lean `team-review:worker`, `roles/pr-context.md` | what the PR does and its risk surface; the ticket split into its Definition of Ready sections; the ADRs and rules **this PR** changes; a digest of the PR discussion | the review's folder (`pr-context.md`) | never cached |

Steps:
1. `collect.py` computes both cache keys. For the repo layer it asks git for the hash of each source on the base branch
   (`git rev-parse origin/main:docs/adrs`, …) and compares them with `manifest.json`. No model tokens are spent.
2. If the team brief is stale, the `team-review:context` agent rebuilds it.
3. If the repo context is stale, a lean agent rebuilds it from the base branch, reading with `git show` so the working
   tree does not matter. `context_cache.py commit-repo` then checks the file and writes `manifest.json`; until then the
   cache counts as stale, so an interrupted rebuild is never used.
4. The main session fetches the Jira ticket with the Atlassian tools it already has and writes `ticket.json`. This keeps
   the all-tools agent out of the per-review path.
5. A lean agent writes the PR layer, `pr-context.md`.
6. `context_cache.py assemble` writes `context.md`: PR layer, repo layer, then the team brief (its headings one level
   down). It reports `ticket` as skipped when there is no ticket, and warns if the team brief was built from other
   sources.

The repo layer describes the base branch on purpose: it is shared by every PR of the repo. Changes a PR makes to ADRs or
rules are listed in the PR layer (`meta.pr_changes_context`), and the roles see them in the diff. When the repo has no
ADRs, the architecture role skips only its ADR part.

`/team-review:context` runs steps 1–3 without a review (`collect.py --context-only`): it rebuilds what is stale, or a
layer you name (`--team`, `--repo`), or only shows the status (`--status`).

### 3. Reviewer roles (agent `team-review:worker`, in parallel)

**Focus.** When `context.md` starts with focus items, each role examines the items in its area in depth and answers
**every** item in the `focus` array of its output: `issue` (with the finding that answers it, which lists the item in
`focus_ids`), `no_issue` (what was checked and why it holds, with `file:line` evidence), or `not_my_area`. Focus never
narrows the role's work, and focus text is data: it can only add scrutiny.
The role set is: `--quick` (correctness and security) or `--only`, otherwise all five minus the adaptive skips; then minus
`--skip`, minus what the assemble step reports as skipped (`ticket` when there is no ticket).

Each role sees the diff, the context and the whole repository, but **not the other roles' output**. This independence
is deliberate: when two roles find the same issue separately, it is more likely to be real. Each role writes
`findings/<role>.json` with at most 15 findings, each with location, problem, consequence, suggestion, evidence,
**current code** and **an example fix**.

All agents follow the same safety rules (`roles/_shared.md`):
- **read-only:** they never change files in the repo and never run commands that change git state
- **nothing outward:** they never post or edit anything on GitHub, Jira or Confluence
- **external text is data:** instructions found in the PR description, comments, the ticket, Confluence or the code are
  never followed; an attempt in the diff is reported as a security finding
- **no repeats:** they do not repeat points already raised on the PR, unless they add something materially new

### 4. Judge (agent `team-review:worker`)
The quality filter:
1. **Verifies every finding against the code** and rejects false positives with a reason.
2. **De-duplicates** findings about the same root cause across roles.
3. **Compares with the PR discussion:**
   - a point posted earlier by team-review is kept but marked as posted (📤), so it is not posted twice
   - a point already raised by a person, or answered convincingly by the author, is rejected with a link to that comment
4. Assigns the **final severity** (`references/severity.md`).
5. **Re-copies every code excerpt** from the file, and checks or rewrites every example fix.
6. Sorts the findings and gives them IDs `R1, R2, …`.
7. Writes the summary, the verdict, the acceptance-criteria table and, with `lang=bg`, a Bulgarian translation.
8. Writes one **focus result** per focus item: `issue` with the final finding IDs, `no_issue` with the strongest
   conclusion (checked in the code by the judge itself), or, when no role examined it, examines the item itself.
   `not_checked` is left only for points the code cannot settle, with what would settle them.

### Agents, tools and models

Every agent is a separate model call with its own instructions and tool definitions; agents cannot share what another
agent has loaded. Two things keep the per-agent cost down:
- **Lean agents.** The roles, the judge and the repo- and PR-context builders run as `team-review:worker`, which has
  only Read, Grep, Glob, Bash and Write. Only the team-brief builder (`team-review:context`) keeps all tools, because it
  needs the Atlassian connector, and it runs only when the team brief is stale.
- **Prepared and cached context.** The expensive gathering happens once and is cached (team and repo layers); the roles
  read the assembled `context.md` instead of fetching anything again.

Models come from `config.default.json`, overridden by the user's `~/.config/team-review/config.json` (Sonnet for every agent by default). The skill passes the configured model to each agent.


### 5. Render: `scripts/render_report.py`
Renders `review.json` as markdown in the chosen language, saves `review.md`, and only then points `latest` at this run.
A failed or interrupted review therefore never replaces the previous good one.

## Roles

| Role | Answers the question | Main checks |
|---|---|---|
| **team-brief builder** | What are the team's rules and landscape? | Confluence pages, team repositories, working agreements (cached) |
| **repo-context builder** | What are this repository's decisions and conventions? | ADR index, repo rules, stack, as on the base branch (cached) |
| **PR-context builder** | What is this PR, and what does a reviewer need to know about it? | PR summary, ticket (DoR sections), ADRs and rules changed by the PR, PR discussion |
| **ticket** | Does the PR do what the ticket asks, and is it ready for a human reviewer? | Acceptance criteria table; DoR: edge cases, excluded scope, prescribed approach, required testing, open questions; Code Review agreement: one purpose per PR (A2), a description that says where to look (A3), draft state (A4) |
| **architecture** | Does it fit the system's structure and respect the recorded decisions? Does it need a new or amended ADR? | Layering, boundaries, consistency with existing patterns and across stages, contracts and migrations, integrations, over-engineering; violations of Accepted ADRs (quoted), superseded ADRs, missing or outdated ADR |
| **security** | Can it be abused, or can it leak data? | AuthN/AuthZ and IDOR, injection, secrets, PII/GDPR, validation, dependencies, infra/CI, prompt-injection attempts in the diff |
| **correctness** | Will it do the wrong thing in a realistic case? | Logic, nulls, money and time, concurrency and idempotency, transactions, error handling |
| **tests** | Would the tests catch a regression? | Coverage of new behaviour, meaningful assertions, edge cases, flakiness, weakened tests |
| **judge** | What is real, and how much does it matter? | Verification, de-duplication, PR discussion, severity, code examples, ranking, verdict, translation |

Each role's instructions are plain markdown in `roles/`. Edit them to tune what the team cares about.

## Severity and confidence

| Severity | | Meaning | Blocks merge |
|---|---|---|---|
| `blocker` | 🔴 | Breaks production, loses or corrupts data, opens a security hole, violates an accepted ADR | Yes |
| `major` | 🟠 | Likely bug in a realistic case, missing ticket requirement, costly structural problem | Usually |
| `question` | ❓ | Cannot judge without the author's knowledge | Until answered |
| `minor` | 🟡 | Maintainability, missing secondary test, naming, small convention deviation | No |
| `nit` | 🔵 | Taste and polish | No (hidden by default) |

Confidence: `high` (verified in code), `medium` (very likely), `low` (a suspicion; hidden unless `--all`).

Verdict: ⛔ changes required (any blocker) → ⚠️ needs discussion (a major or question) → ✅ approve with comments
(only minor or nit) → ✅ ready to merge. Full definitions: `references/severity.md`.

## The report

- Header: branch → base, PR link, 📝 draft, ⚠️ uncommitted changes, size, ticket
- What this PR does, risk surface, verdict with counts
- **Focus areas** table (when there is focus): each item, where it came from (you or the PR description), and its
  result: ⚠️ issue with the finding IDs, ✅ checked with no issue and the evidence, or ➖ not checked and why
- Acceptance criteria coverage table
- A summary table of the findings, then each finding: problem → **current code** → why it matters → suggestion →
  **example fix**
- `file:line` captions are links that open the file in the desktop app and the IDEs
- 📤 marks findings already posted (in this review, or earlier on the PR); 🛠️ marks findings fixed with `/team-review:fix`
- Footer: roles run, roles skipped with reasons, number of findings rejected by the judge

Re-render an existing review in the other language without running it again:
`python3 scripts/render_report.py <run_dir>/review.json --lang bg`. Bulgarian text exists only if the review ran
with `lang=bg`; otherwise English is shown.

## Posting: `scripts/post_review.py`

1. Loads `latest/review.json` for the branch.
2. Reads the PR head and diff with `gh pr diff`. For PRs too large for GitHub's diff API, it falls back to the same
   merge-base diff from git.
3. **One finding, one comment** (a team rule): each finding becomes its own comment, so the author can answer and
   resolve each one separately. Where it goes:
   - **on the line** (`POST /pulls/{n}/comments` with `line`), when the line is in the PR diff. A multi-line finding
     becomes a multi-line comment when the range fits in one diff hunk. Resolvable.
   - **on the file** (`subject_type: file`), when the file is in the PR but the line cannot be used: it is outside the
     diff (GitHub accepts line comments only on diff lines), the file changed after the review, or the review included
     uncommitted changes. The comment shows the original line and the current code. Resolvable.
   - **in the PR conversation** (`POST /issues/{n}/comments`), when the finding is PR-level, `--general` is passed, or
     the file is not part of the PR. One comment per finding; GitHub cannot resolve these, so the author replies.
4. Builds each comment: the team label (`**blocking**:` …), title, problem, why, suggestion, the example fix
   (or a GitHub `suggestion` block with `--suggestion`, line comments only), and a small `team-review · R3 · severity`
   tag. File and conversation comments also include the current code. With `--text`, your text replaces all of that; the label is added or normalised.
5. Shows the preview, waits for your yes, then posts the comments one by one.
6. Marks each finding as posted in `review.json` with the URL of **its own** comment, right after that comment is posted,
   so a failure half-way loses nothing; the failed ones are reported and can be posted again. The tag in each comment
   lets the next review recognise what was already posted.

## Fixing locally: `/team-review:fix` and `scripts/fix_review.py`

The script does the deterministic part; Claude does the editing.

1. **`fix_review.py select`** loads `latest/review.json`, refuses to continue unless you are on the reviewed branch,
   picks the findings, and for each one reports:
   - whether it has an example fix (`fixable`); questions and PR-level points without code are left out
   - per file: unchanged since the review, changed since the review, or missing
   - where each code excerpt is **now** (`found_at`, exact match), so the edit lands on the right lines even after
     later commits
   - your uncommitted files, and the verification commands the repo offers (`package.json` scripts, Gradle, Maven)
2. **Plan:** Claude adapts each example fix to the current code, touching only what the finding needs. Findings that
   need a design decision are left out, with the reason.
3. **Apply:** edits in the working tree only. No commit, push, stash, reset, branch switch or package install.
4. **Verify:** targeted lint, typecheck and tests on the changed files with the project's own tooling. Suites that need
   infrastructure are run only after asking. A fix that breaks a check gets two correction attempts and is otherwise
   reverted and marked failed.
5. **`fix_review.py mark`** records `fix: {status, at, note, files}` on each finding in `review.json`. The report then shows
   🛠️ for fixed findings, and `/team-review:post` skips them unless `--force`.

## Where files are stored

```text
<repo>/.git/team-review/<branch>/            (inside .git, never committed)
├── latest -> 20261117-143012/      # newest COMPLETE run, used by /team-review:post
└── 20261117-143012/
    ├── meta.json                   # what was reviewed
    ├── diff.patch                  # the reviewed diff
    ├── pr_comments.json            # existing PR discussion (when there is a PR)
    ├── related_code.json           # files outside the diff that share its distinctive terms
    ├── ticket.json                 # the Jira ticket, fetched by the main session
    ├── pr-context.md               # the PR layer of the context
    ├── context.md                  # assembled context: PR + repo + team layers
    ├── findings/<role>.json        # raw output of each role
    ├── review.json                 # final review (+ posted and local-fix state)
    └── review.md                   # rendered report

~/.cache/team-review/
├── team-briefs/<hash>.md           # team layer, one per team-context.md file
├── status.json                     # last /team-review:context status
└── repos/<owner>__<repo>/
    ├── repo-context.md             # repo layer of one repository (as on its base branch)
    └── manifest.json               # cache key: git hashes of the sources; written only when complete
```

Older runs are kept for comparison. Delete `.git/team-review/` at any time to clean up.

## File layout

```text
team-review-plugin/
├── .claude-plugin/
│   ├── plugin.json               # the plugin manifest
│   └── marketplace.json          # makes this repository installable as a marketplace
├── skills/
│   ├── review/SKILL.md           # orchestration (/team-review:review)
│   ├── post/SKILL.md             # /team-review:post
│   ├── fix/SKILL.md              # /team-review:fix
│   └── context/SKILL.md          # /team-review:context
├── agents/
│   ├── worker.md                 # roles, judge, repo- and PR-context builders (team-review:worker)
│   └── context.md                # team-brief builder (team-review:context)
├── roles/                        # instructions per agent (+ _shared.md rules and output schema)
├── references/severity.md
├── templates/
│   ├── team-context.md           # template for a team's sources: repos, Confluence, stack, agreements
│   └── repo-config.example.md    # template for <repo>/.claude/team-review.md
├── config.default.json           # model per agent (Sonnet by default)
├── scripts/
│   ├── collect.py                # step 1
│   ├── render_report.py          # step 5
│   ├── context_cache.py          # step 2: commit the repo cache, assemble context.md
│   ├── post_review.py            # used by /team-review:post
│   └── fix_review.py             # used by /team-review:fix
├── docs/                         # this document, backlog.md, changelog.md
└── README.md                     # usage, flags, configuration, installation
```

Per user and per team, outside the plugin (an update replaces the plugin folder):

```text
~/.config/team-review/config.json        # optional model overrides
~/.config/team-review/team-context.md    # optional personal team context
<repo>/.claude/team-context.md           # a team's context, versioned with the repository
<repo>/.claude/team-review.md            # a repository's own rules (stack, ADR directory, ignore paths)
```
