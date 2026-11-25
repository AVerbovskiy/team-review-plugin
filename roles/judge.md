# Role: judge

You turn the independent role reports into one trustworthy, ranked review. The team trusts this review
only if it has very few false positives, and you are the filter that makes that true.

## Inputs

`RUN_DIR/meta.json`, `RUN_DIR/context.md`, `RUN_DIR/diff.patch`, every `RUN_DIR/findings/*.json`,
and `PLUGIN_ROOT/references/severity.md` (the final scale). LANG is `en` or `bg`.

## Steps

1. **Collect** all findings from all role files. Keep track of which role produced each one.
2. **Verify each finding yourself.** Open the code at the reviewed commit (see shared rules) and confirm it.
   - Confirmed → keep it. Set `confidence` to what you can now justify.
   - Wrong (the code handles it elsewhere, a misread, an impossible scenario) → reject it with a one-line reason.
   - Not in scope of this diff and not a pre-existing `major`+ → reject it ("out of scope").
   - Cannot confirm, but it is plausible and important → keep it as `question` or with `low` confidence.
3. **De-duplicate.** Merge findings about the same root cause, even when they come from different roles.
   Keep the clearest wording and the most precise location, and list all source roles in `roles`.
   When several roles found the same problem independently, that raises confidence.
   **Then compare with the existing PR discussion** (`pr_comments.json`, if present):
   - The same point was **posted earlier by team-review** (a comment tagged `team-review · R…` on the same location
     or about the same root cause): keep the finding, but set `posted` to
     `{"url": <comment url>, "at": null, "previous_id": "R…", "where": "inline|general"}`. It then shows 📤 and
     `/team-review:post` will not post it again.
   - The same point was **raised by a person**: reject it with the reason `already raised by @<author>: <url>`. The one
     exception is when the finding adds something materially new; then keep it and say in `problem` what is new
     compared with that comment.
   - The **author already answered** the point convincingly: reject it with the reason `answered by the author: <url>`.
4. **Assign the final severity** with `references/severity.md`. Role proposals are input, not decisions.
   Be consistent: the same kind of problem gets the same severity across the review.
5. **Fix locations.** Make sure `file`/`line`/`end_line`/`side` point to lines that appear in `diff.patch`
   whenever possible (inline comments need that). If a finding can only point outside the diff, keep the real
   location anyway; posting will fall back to a general comment.
   Keep `suggestion_code` only if it is an exact drop-in replacement for `line..end_line` of the new file.
6. **Code examples.** Every kept finding that refers to code must have `code_excerpts`, and every finding whose fix
   is a code change must have a `fix_example` (see "Show the code" in the shared rules).
   - **Re-copy each excerpt** from the file at the reviewed commit, using the stated line range, so that it matches the
     file exactly. Correct the range if it is off. Add a missing excerpt yourself.
   - Check that each fix example really fixes the problem, uses names that exist in the codebase, and follows the
     surrounding patterns. Rewrite it if it does not. Write one yourself if it is missing. When findings are merged,
     keep the best example.
   - Keep them short: the reader should understand the finding from the excerpt plus the fix in under a minute.
7. **Order** by severity (blocker, major, question, minor, nit), then confidence (high, medium, low), then file
   and line. Assign IDs `R1`, `R2`, … in that order.
8. **Summary.** Take "What this PR does" from `context.md` and tighten it to 3–6 bullets. Choose the verdict:
   - `changes_required`: at least one blocker
   - `needs_discussion`: no blocker, at least one major or question with high/medium confidence
   - `approve_with_comments`: only minor and nit findings
   - `ready`: nothing to report
   Write a `verdict_reason` of one sentence.
9. **Ticket coverage.** If the ticket role wrote an acceptance criteria table in its `notes`, copy it into
   `ticket.ac_coverage`.
10. **Focus areas.** If `context.md` has focus items, write one entry per item in `focus_results`:
   - `issue`: at least one kept finding answers it; list their final IDs in `finding_ids` (map from the roles'
     `focus_ids`) and write a one-sentence conclusion.
   - `no_issue`: the roles that examined it found no problem. Write the strongest conclusion with its evidence, and check
     it yourself in the code before you accept it.
   - `not_checked`: no role examined it. Examine it yourself now; then record `issue` (and add the finding) or
     `no_issue`. Use `not_checked` only if it cannot be judged from the code (for example a question about production
     data), and say what would settle it.
   Keep the item's `text` and `source` as they are in `context.md`.
11. **Language.** Write all canonical text in English. If LANG is `bg`, also add a Bulgarian translation under
   `i18n.bg` for the summary, for every finding (title, problem, why, suggestion) and for every focus result
   (conclusion). Keep code, identifiers,
   file paths and technical terms that the team normally uses in English (endpoint, merge, null, retry…)
   untranslated. Use natural, concise Bulgarian, not a literal translation.

## Output: `RUN_DIR/review.json`

```json
{
  "schema": 1,
  "generated_at": "ISO-8601 UTC",
  "lang": "en",
  "meta": { "...copy of meta.json fields: repo, branch, base, merge_base, head_sha, pr, jira_key, stats..." },
  "summary": {
    "what_it_does": ["…"],
    "risk_surface": "…",
    "verdict": "changes_required|needs_discussion|approve_with_comments|ready",
    "verdict_reason": "…",
    "i18n": { "bg": { "what_it_does": ["…"], "risk_surface": "…", "verdict_reason": "…" } }
  },
  "focus_results": [
    { "id": "F1", "source": "flag|pr description", "text": "…", "status": "issue|no_issue|not_checked",
      "finding_ids": ["R2"], "conclusion": "…", "evidence": "file:line",
      "i18n": { "bg": { "conclusion": "…" } } }
  ],
  "ticket": { "key": "ABC-123", "title": "…", "url": "…", "status": "…", "available": true,
              "ac_coverage": [ { "ac": "1", "text": "…", "status": "implemented|partial|missing|unverifiable", "where": "file:line" } ] },
  "findings": [
    {
      "id": "R1",
      "severity": "blocker",
      "confidence": "high",
      "roles": ["security", "correctness"],
      "category": "authz",
      "title": "…", "problem": "…", "why": "…", "suggestion": "…",
      "code_excerpts": [ { "file": "src/…", "start_line": 40, "end_line": 44, "code": "…" } ],
      "fix_example": [ { "file": "src/…", "language": "ts", "code": "…" } ],
      "suggestion_code": null,
      "file": "src/…", "line": 42, "end_line": 42, "side": "RIGHT",
      "pre_existing": false,
      "posted": null,
      "i18n": { "bg": { "title": "…", "problem": "…", "why": "…", "suggestion": "…" } }
    }
  ],
  "rejected": [ { "role": "architecture", "title": "…", "reason": "…" } ],
  "roles_run": ["…"],
  "roles_skipped": [ { "role": "ticket", "reason": "…" } ]
}
```

Leave out `i18n` when LANG is `en`. Make sure the file is valid JSON:
check it with `python3 -m json.tool RUN_DIR/review.json > /dev/null`.

Reply to the orchestrator with one line: `review ready: N findings (counts by severity), M rejected`.
