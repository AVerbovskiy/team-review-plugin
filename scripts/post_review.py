#!/usr/bin/env python3
"""team-review: publish selected findings from review.json as one GitHub PR review.

Usage:
  post_review.py [--review PATH | --branch NAME] [--pr N] [--lang en|bg]
                 [--text TEXT] [--general] [--suggestion] [--force] [--dry-run] SELECTOR...

SELECTOR: finding IDs (R1 r3 …) or the keywords blockers / majors / questions.
Exit codes: 0 ok, 1 error, 3 translation missing (message on stderr names the IDs).
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SEV_ICON = {"blocker": "🔴", "major": "🟠", "question": "❓", "minor": "🟡", "nit": "🔵"}
LABELS = {
    "en": {"why": "Why it matters", "suggestion": "Suggestion", "fix": "Example fix",
           "moved": "(file changed since the review; originally {loc})",
           "uncommitted": "(reviewed together with uncommitted local changes; originally {loc})"},
    "bg": {"why": "Защо е важно", "suggestion": "Предложение", "fix": "Примерна поправка",
           "moved": "(файлът е променен след ревюто; първоначално {loc})",
           "uncommitted": "(ревюирано заедно с некомитнати локални промени; първоначално {loc})"},
}
sys.dont_write_bytecode = True  # keep the skill folder free of __pycache__ (it gets shared)
from render_report import code_block, fence_lang  # noqa: E402


def excerpt_caption(ex):
    """Plain caption for GitHub: relative markdown links do not resolve in PR comments."""
    if not ex.get("file"):
        return None
    rng = ex.get("start_line")
    if rng and ex.get("end_line") and ex["end_line"] != rng:
        rng = f"{rng}-{ex['end_line']}"
    return f"`{ex['file']}:{rng}`" if rng else f"`{ex['file']}`"

KEYWORDS = {"blockers": {"blocker"}, "majors": {"blocker", "major"}, "questions": {"question"}}


class UserError(Exception):
    pass


def run(cmd, input_text=None, check=True):
    p = subprocess.run(cmd, capture_output=True, text=True, input=input_text)
    if check and p.returncode != 0:
        raise UserError(f"`{' '.join(cmd[:4])} …` failed: {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout if p.returncode == 0 else None


def locate_review(branch):
    common = run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"]).strip()
    if not branch:
        branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", branch)
    path = Path(common) / "team-review" / safe / "latest" / "review.json"
    if not path.exists():
        raise UserError(f"No review found for branch '{branch}' ({path}). Run /team-review:review first.")
    return path


def parse_diff(text):
    """Return {path: {"RIGHT": set(lines), "LEFT": set(lines), "hunks": [(side, start, end)]}}."""
    files, path, old_path, o, n, in_hunk = {}, None, None, 0, 0, False
    for line in text.splitlines():
        if line.startswith("diff --git "):
            path, old_path, in_hunk = None, None, False
            continue
        if not in_hunk and line.startswith("--- "):
            p = line[4:].strip()
            old_path = None if p == "/dev/null" else re.sub(r"^a/", "", p)
            continue
        if not in_hunk and line.startswith("+++ "):
            p = line[4:].strip()
            path = old_path if p == "/dev/null" else re.sub(r"^b/", "", p)
            files.setdefault(path, {"RIGHT": set(), "LEFT": set(), "hunks": []})
            continue
        m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if m and path:
            o, n, in_hunk = int(m.group(1)), int(m.group(2)), True
            files[path]["hunks"].append([n, n - 1])
            continue
        if not in_hunk or path is None:
            continue
        if line.startswith("diff --git"):
            in_hunk = False
        elif line.startswith("+"):
            files[path]["RIGHT"].add(n); files[path]["hunks"][-1][1] = n; n += 1
        elif line.startswith("-"):
            files[path]["LEFT"].add(o); o += 1
        elif line.startswith("\\"):
            pass
        else:  # context line (may be empty)
            files[path]["RIGHT"].add(n); files[path]["LEFT"].add(o)
            files[path]["hunks"][-1][1] = n; n += 1; o += 1
    return files


def pr_diff(pr_number, base):
    """The PR diff from GitHub; for PRs too large for the API, the same merge-base diff from git."""
    out = run(["gh", "pr", "diff", str(pr_number)], check=False)
    if out is not None:
        return out, "github"
    ref = f"refs/team-review/pr-{pr_number}"
    run(["git", "fetch", "--quiet", "origin", f"+refs/pull/{pr_number}/head:{ref}", base])
    return run(["git", "diff", "--no-color", "--no-ext-diff", "-M", f"origin/{base}...{ref}"]), "git (PR too large for the GitHub diff API)"


def same_hunk(fileinfo, a, b):
    return any(s <= a <= e and s <= b <= e for s, e in fileinfo["hunks"])


def text_of(f, lang, key):
    if lang != "en":
        return ((f.get("i18n") or {}).get(lang) or {}).get(key)
    return f.get(key)


# Every comment says whether it blocks the merge.
PREFIX = {"blocker": "blocking", "major": "blocking", "question": "question", "minor": "suggestion", "nit": "nit"}
PREFIX_RE = re.compile(r"^\s*(?:\*\*)?(blocking|question|suggestion|nit)(?:\*\*)?\s*:\s*(?:\*\*)?", re.IGNORECASE)


def team_prefix(name):
    """The team writes the label in bold, followed by a colon: **suggestion**: text"""
    return f"**{name}**:"


def with_prefix(f, text):
    """Prefix custom text with the team label; an existing label (bold or not) is normalised to the team style."""
    m = PREFIX_RE.match(text)
    if m:  # "nit: x", "**nit:** x", "**nit**: x" -> "**nit**: x"
        return f"{team_prefix(m.group(1).lower())} {text[m.end():].lstrip()}"
    return f"{team_prefix(PREFIX.get(f['severity'], 'suggestion'))} {text}"


def render_body(f, lang, use_suggestion, note="", general=False):
    t = LABELS[lang]
    parts = [f"{team_prefix(PREFIX.get(f['severity'], 'suggestion'))} {text_of(f, lang, 'title')}" + (f" {note}" if note else "")]
    parts.append(text_of(f, lang, "problem") or "")
    if general:  # inline comments already sit on the code; general ones need to show it
        for ex in f.get("code_excerpts") or []:
            parts.append(code_block(ex.get("code"), fence_lang(ex.get("file")), excerpt_caption(ex)))
    if text_of(f, lang, "why"):
        parts.append(f"**{t['why']}:** {text_of(f, lang, 'why')}")
    if text_of(f, lang, "suggestion"):
        parts.append(f"**{t['suggestion']}:** {text_of(f, lang, 'suggestion')}")
    if use_suggestion and f.get("suggestion_code"):
        parts.append("```suggestion\n" + f["suggestion_code"].rstrip("\n") + "\n```")
    else:
        fixes = f.get("fix_example") or []
        if fixes:
            parts.append(f"**{t['fix']}:**")
            for fx in fixes:
                parts.append(code_block(fx.get("code"), fx.get("language") or fence_lang(fx.get("file")),
                                        f"`{fx['file']}`" if fx.get("file") else None))
    parts.append(f"<sub>team-review · {f['id']} · {SEV_ICON.get(f['severity'], '')} {f['severity']}</sub>")
    return "\n\n".join(p.rstrip("\n") for p in parts if p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("selectors", nargs="+")
    ap.add_argument("--review")
    ap.add_argument("--branch")
    ap.add_argument("--pr", type=int)
    ap.add_argument("--lang", default="en", choices=sorted(LABELS))
    ap.add_argument("--text")
    ap.add_argument("--general", action="store_true")
    ap.add_argument("--suggestion", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-post findings already posted")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    review_path = Path(a.review) if a.review else locate_review(a.branch)
    review = json.loads(review_path.read_text())
    findings = {f["id"].upper(): f for f in review.get("findings", [])}

    selected = []
    for s in a.selectors:
        key = s.lower().strip(",")
        if key in KEYWORDS:
            selected += [f for f in review["findings"] if f["severity"] in KEYWORDS[key]]
        elif s.upper().strip(",") in findings:
            selected.append(findings[s.upper().strip(",")])
        else:
            raise UserError(f"Unknown finding '{s}'. Known: {', '.join(findings)}; keywords: {', '.join(KEYWORDS)}.")
    seen, uniq = set(), []
    for f in selected:
        if f["id"] not in seen:
            seen.add(f["id"]); uniq.append(f)
    selected = uniq
    if not selected:
        raise UserError("Nothing selected.")
    if a.text and len(selected) != 1:
        raise UserError("--text replaces the text of ONE finding; select exactly one ID.")

    def skip_reason(f):
        if a.force:
            return None
        if f.get("posted"):
            return "already posted"
        if (f.get("fix") or {}).get("status") == "fixed":
            return "fixed locally with /team-review:fix"
        return None
    skipped = [f"{f['id']} ({skip_reason(f)})" for f in selected if skip_reason(f)]
    selected = [f for f in selected if not skip_reason(f)]
    if not selected:
        raise UserError(f"Nothing to post: {', '.join(skipped)}. Use --force to post anyway.")

    if a.lang != "en" and not a.text:
        missing = [f["id"] for f in selected if not text_of(f, a.lang, "title")]
        if missing:
            print(f"team-review: missing '{a.lang}' translation for: {', '.join(missing)}", file=sys.stderr)
            sys.exit(3)

    pr_number = a.pr or ((review.get("meta") or {}).get("pr") or {}).get("number")
    if not pr_number:
        branch = (review.get("meta") or {}).get("branch")
        info = json.loads(run(["gh", "pr", "view", branch, "--json", "number"]) or "null") if branch else None
        pr_number = info and info.get("number")
    if not pr_number:
        raise UserError("No PR found for this branch. Open a PR first or pass --pr N.")

    pr = json.loads(run(["gh", "pr", "view", str(pr_number), "--json", "number,url,headRefOid,state,baseRefName"]))
    head = pr["headRefOid"]
    meta = review.get("meta") or {}
    reviewed = meta.get("head_sha")
    uncommitted = bool(meta.get("includes_uncommitted"))
    diff_text, diff_source = pr_diff(pr_number, pr["baseRefName"])
    diff_info = parse_diff(diff_text)

    changed_files = None
    if reviewed and reviewed != head:
        run(["git", "fetch", "--quiet", "origin", f"+refs/pull/{pr_number}/head:refs/team-review/pr-{pr_number}"], check=False)
        out = run(["git", "diff", "--name-only", reviewed, head], check=False)
        changed_files = set(out.split()) if out is not None else None  # None = unknown → treat all as changed

    # Team rule: one finding = one comment, so the author can answer and resolve each one on its own.
    # Every finding is posted as its own comment, never combined with another:
    #   line → a review comment on the line (a resolvable thread)
    #   file → a review comment on the file, when the file is in the PR but the line cannot be used (resolvable thread)
    #   pr   → a PR conversation comment, when the finding is PR-level or its file is not part of the PR
    #          (GitHub cannot resolve these; the author replies instead)
    t = LABELS[a.lang]
    posts, plan = [], []
    for f in selected:
        file, line, end, side = f.get("file"), f.get("line"), f.get("end_line"), (f.get("side") or "RIGHT")
        loc = f"{file}:{line}" if file and line else (file or "PR")
        reason = None
        if a.general:
            reason = "--general"
        elif uncommitted and file and line:
            reason = "review included uncommitted changes; line numbers may not match the PR"
        elif not file or not line:
            reason = "PR-level finding"
        elif file not in diff_info or line not in diff_info[file][side]:
            reason = "line not in the PR diff"
        elif reviewed and reviewed != head and (changed_files is None or file in changed_files):
            reason = "file changed since the review"

        if reason is None:
            where = "line"
        elif reason != "--general" and file and file in diff_info:
            where = "file"
        else:
            where = "pr"

        note = ""
        if reason == "file changed since the review":
            note = t["moved"].format(loc=f"`{loc}`")
        elif reason and reason.startswith("review included"):
            note = t["uncommitted"].format(loc=f"`{loc}`")
        if a.text:
            body = with_prefix(f, a.text)
            if where != "line" and file:
                body += f"\n\n<sub>`{loc}`</sub>"
        else:
            body = render_body(f, a.lang, a.suggestion and where == "line", note, general=where != "line")

        if where == "line":
            c = {"commit_id": head, "path": file, "side": side, "body": body,
                 "line": end if end and end > line and same_hunk(diff_info[file], line, end) else line}
            if c["line"] != line:
                c["start_line"], c["start_side"] = line, side
            endpoint = f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/comments"
        elif where == "file":
            c = {"commit_id": head, "path": file, "subject_type": "file", "body": body}
            endpoint = f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/comments"
        else:
            c = {"body": body}
            endpoint = f"repos/{{owner}}/{{repo}}/issues/{pr_number}/comments"
        posts.append((f, where, endpoint, c))
        plan.append({"id": f["id"], "where": where, "reason": reason, "location": loc,
                     "resolvable": where != "pr"})

    result = {"pr": pr["url"], "head_sha": head, "reviewed_sha": reviewed,
              "stale": bool(reviewed and reviewed != head), "includes_uncommitted": uncommitted,
              "diff_source": diff_source, "already_posted_skipped": skipped, "plan": plan}
    if a.dry_run:
        result["comments"] = [{"id": f["id"], "where": w, **c} for f, w, _, c in posts]
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    posted, failed = [], []
    for f, where, endpoint, payload in posts:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            json.dump(payload, tmp, ensure_ascii=False)
        try:
            resp = json.loads(run(["gh", "api", "-X", "POST", endpoint, "--input", tmp.name]))
        except UserError as e:
            failed.append({"id": f["id"], "where": where, "error": str(e)})
            continue
        finally:
            Path(tmp.name).unlink(missing_ok=True)
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        findings[f["id"].upper()]["posted"] = {"url": resp.get("html_url"), "at": now, "where": where,
                                               "comment_id": resp.get("id"), "custom_text": bool(a.text)}
        # Saved after every comment, so a failure half-way never loses what was already posted.
        review_path.write_text(json.dumps(review, indent=2, ensure_ascii=False))
        posted.append({"id": f["id"], "where": where, "url": resp.get("html_url")})

    result["posted"] = posted
    result["failed"] = failed
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except UserError as e:
        print(f"team-review: {e}", file=sys.stderr)
        sys.exit(1)
