#!/usr/bin/env python3
"""team-review: helper for /team-review:fix (apply review findings locally).

  fix_review.py select SELECTOR... [--review PATH | --branch NAME] [--force]
      Validates that you are on the reviewed branch, picks the findings, and for each one reports whether it
      has an example fix, whether its file changed since the review, and where its code excerpt is now.
      Prints JSON. Changes nothing.

  fix_review.py mark ID... --status fixed|skipped|failed [--note TEXT] [--files a,b] [--review PATH | --branch NAME]
      Records the outcome in review.json, so the report shows it and /team-review:post skips fixed findings.

SELECTOR: finding IDs (R1 r3 …) or the keywords blockers / majors / all.
Exit codes: 0 ok, 1 error (message on stderr).
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

KEYWORDS = {"blockers": {"blocker"}, "majors": {"blocker", "major"},
            "all": {"blocker", "major", "question", "minor", "nit"}}


class UserError(Exception):
    pass


def git(*args, check=True):
    p = subprocess.run(["git", *args], capture_output=True, text=True)
    if p.returncode != 0:
        if check:
            raise UserError(f"`git {' '.join(args[:3])} …` failed: {p.stderr.strip()}")
        return None
    return p.stdout


def locate_review(path, branch):
    if path:
        return Path(path)
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    branch = branch or git("rev-parse", "--abbrev-ref", "HEAD").strip()
    p = Path(common) / "team-review" / re.sub(r"[^A-Za-z0-9._-]+", "_", branch) / "latest" / "review.json"
    if not p.exists():
        raise UserError(f"No review found for branch '{branch}'. Run /team-review:review first.")
    return p


def select_findings(review, selectors):
    by_id = {f["id"].upper(): f for f in review.get("findings", [])}
    out = []
    for s in selectors:
        key = s.strip(",")
        if key.lower() in KEYWORDS:
            out += [f for f in review["findings"] if f["severity"] in KEYWORDS[key.lower()]]
        elif key.upper() in by_id:
            out.append(by_id[key.upper()])
        else:
            raise UserError(f"Unknown finding '{s}'. Known: {', '.join(by_id)}; keywords: {', '.join(KEYWORDS)}.")
    seen, uniq = set(), []
    for f in out:
        if f["id"] not in seen:
            seen.add(f["id"])
            uniq.append(f)
    return uniq


def find_excerpt(root, excerpt):
    """Where the excerpt's code is in the working tree now: list of 1-based start lines (exact match, trailing spaces ignored)."""
    path = root / (excerpt.get("file") or "")
    if not excerpt.get("file") or not path.is_file():
        return None
    want = [l.rstrip() for l in (excerpt.get("code") or "").rstrip("\n").splitlines()]
    if not want:
        return None
    have = [l.rstrip() for l in path.read_text(errors="replace").splitlines()]
    n = len(want)
    return [i + 1 for i in range(len(have) - n + 1) if have[i:i + n] == want]


def detect_checks(root):
    """Commands the repo offers for verification, so fixes can be checked with the project's own tooling."""
    checks = {}
    pkg = root / "package.json"
    if pkg.exists():
        try:
            scripts = json.loads(pkg.read_text()).get("scripts", {})
        except json.JSONDecodeError:
            scripts = {}
        pm = "pnpm" if (root / "pnpm-lock.yaml").exists() else "yarn" if (root / "yarn.lock").exists() else "npm"
        checks["package_manager"] = pm
        checks["scripts"] = {k: v for k, v in scripts.items()
                             if re.search(r"lint|type|tsc|test|format|check|build", k, re.I)}
    if (root / "gradlew").exists():
        checks["gradle"] = "./gradlew"
    if (root / "pom.xml").exists():
        checks["maven"] = "mvn"
    return checks


def cmd_select(a):
    review_path = locate_review(a.review, a.branch)
    review = json.loads(review_path.read_text())
    meta = review.get("meta") or {}
    root = Path(git("rev-parse", "--show-toplevel").strip())
    current = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    if meta.get("branch") and meta["branch"] != current:
        raise UserError(f"The review is for '{meta['branch']}', but you are on '{current}'. "
                        f"Switch to {meta['branch']} first: fixes are applied to the reviewed branch only.")

    reviewed = meta.get("head_sha")
    known = bool(reviewed) and git("cat-file", "-e", f"{reviewed}^{{commit}}", check=False) is not None
    dirty = [l[3:] for l in (git("status", "--porcelain", "--untracked-files=no") or "").splitlines()]

    picked, skipped = [], []
    for f in select_findings(review, a.selectors):
        status = (f.get("fix") or {}).get("status")
        if status == "fixed" and not a.force:
            skipped.append({"id": f["id"], "reason": "already fixed locally (use --force to redo)"})
            continue
        fixable = bool(f.get("fix_example") or f.get("suggestion_code"))
        files = sorted({x.get("file") for x in (f.get("code_excerpts") or []) + (f.get("fix_example") or []) if x.get("file")}
                       | ({f["file"]} if f.get("file") else set()))
        state = {}
        for path in files:
            if not (root / path).exists():
                state[path] = "missing (new file to create, or removed since the review)"
            elif not known:
                state[path] = "unknown (reviewed commit not available locally)"
            else:
                same = subprocess.run(["git", "diff", "--quiet", reviewed, "--", path]).returncode == 0
                state[path] = "unchanged since the review" if same else "changed since the review"
        excerpts = [{"file": x.get("file"), "reviewed_start_line": x.get("start_line"),
                     "found_at": find_excerpt(root, x)} for x in f.get("code_excerpts") or []]
        picked.append({
            "id": f["id"], "severity": f["severity"], "title": f.get("title"), "fixable": fixable,
            "why_not_fixable": None if fixable else (
                "a question for the author" if f["severity"] == "question" else "no example fix (not a code change)"),
            "previous_fix": f.get("fix"), "posted": bool(f.get("posted")),
            "file": f.get("file"), "line": f.get("line"), "end_line": f.get("end_line"),
            "files": state, "excerpts": excerpts,
            "problem": f.get("problem"), "suggestion": f.get("suggestion"),
            "code_excerpts": f.get("code_excerpts"), "fix_example": f.get("fix_example"),
            "suggestion_code": f.get("suggestion_code"),
        })
    if not picked and not skipped:
        raise UserError("Nothing selected.")

    print(json.dumps({
        "review_path": str(review_path), "repo_root": str(root), "branch": current,
        "reviewed_sha": reviewed, "head_now": git("rev-parse", "HEAD").strip(),
        "includes_uncommitted": bool(meta.get("includes_uncommitted")),
        "uncommitted_files": dirty, "checks": detect_checks(root),
        "findings": picked, "skipped": skipped,
    }, indent=2, ensure_ascii=False))


def cmd_mark(a):
    review_path = locate_review(a.review, a.branch)
    review = json.loads(review_path.read_text())
    by_id = {f["id"].upper(): f for f in review.get("findings", [])}
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    files = [x for x in (a.files or "").split(",") if x]
    for i in a.ids:
        f = by_id.get(i.upper().strip(","))
        if not f:
            raise UserError(f"Unknown finding '{i}'.")
        f["fix"] = {"status": a.status, "at": now, "note": a.note, "files": files}
    review_path.write_text(json.dumps(review, indent=2, ensure_ascii=False))
    print(json.dumps({"marked": [i.upper() for i in a.ids], "status": a.status}))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("selectors", nargs="+")
    s.add_argument("--force", action="store_true")
    m = sub.add_parser("mark")
    m.add_argument("ids", nargs="+")
    m.add_argument("--status", required=True, choices=["fixed", "skipped", "failed"])
    m.add_argument("--note")
    m.add_argument("--files")
    for p in (s, m):
        p.add_argument("--review")
        p.add_argument("--branch")
    a = ap.parse_args()
    (cmd_select if a.cmd == "select" else cmd_mark)(a)


if __name__ == "__main__":
    try:
        main()
    except UserError as e:
        print(f"team-review: {e}", file=sys.stderr)
        sys.exit(1)
