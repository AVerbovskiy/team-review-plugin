#!/usr/bin/env python3
"""team-review: collect the inputs for a review run.

Resolves the target (current branch, branch name, PR number or PR URL), the base branch,
the merge-base, the diff, PR metadata, the Jira key and the team-brief cache status.
Writes RUN_DIR/meta.json and RUN_DIR/diff.patch and prints meta.json to stdout.
Exit code 0 on success, 1 on a user-facing error (message on stderr).
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CACHE_MAX_AGE_DAYS = 7
LARGE_DIFF_LINES = 4000
STACK_MARKERS = {
    "build.gradle.kts": "Gradle (Kotlin DSL)",
    "build.gradle": "Gradle",
    "pom.xml": "Maven",
    "package.json": "Node.js",
    "tsconfig.json": "TypeScript",
    "go.mod": "Go",
    "pyproject.toml": "Python",
    "requirements.txt": "Python",
    "Cargo.toml": "Rust",
    "Gemfile": "Ruby",
    "Dockerfile": "Docker",
    "Chart.yaml": "Helm",
    "dataform.json": "Dataform",
    "workflow_settings.yaml": "Dataform",
}


class UserError(Exception):
    pass


def run(cmd, cwd=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        if check:
            raise UserError(f"`{' '.join(cmd)}` failed: {p.stderr.strip() or p.stdout.strip()}")
        return None
    return p.stdout


def git(*args, check=True):
    out = run(["git", *args], check=check)
    return out.strip() if out is not None else None


def ref_ok(ref):
    return bool(ref) and git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)


def gh_available():
    return shutil.which("gh") is not None


def gh_json(args):
    if not gh_available():
        return None
    out = run(["gh", *args], check=False)
    try:
        return json.loads(out) if out else None
    except json.JSONDecodeError:
        return None


PR_FIELDS = "number,url,title,body,headRefName,headRefOid,baseRefName,state,isDraft,author,headRepositoryOwner,isCrossRepository"


def parse_target(t):
    if not t:
        return ("current", None)
    m = re.fullmatch(r"#?(\d+)", t) or re.search(r"/pull/(\d+)", t)
    if m:
        return ("pr", int(m.group(1)))
    return ("branch", t)


def jira_key(branch):
    m = re.search(r"\b([A-Z][A-Z0-9]+-\d+)", branch)
    if not m:
        m = re.search(r"(?:^|[/_-])([a-zA-Z][a-zA-Z0-9]+-\d+)", branch)
    return m.group(1).upper() if m else None


def read_ignore_paths(config_path):
    """Bullets under a '## Ignore paths' heading in .claude/team-review.md."""
    if not config_path or not config_path.exists():
        return []
    paths, in_section = [], False
    for line in config_path.read_text().splitlines():
        if line.startswith("#"):
            in_section = line.lstrip("#").strip().lower() == "ignore paths"
            continue
        if in_section:
            m = re.match(r"\s*[-*]\s+`?([^`\s]+)`?", line)
            if m:
                paths.append(m.group(1))
    return paths


def adr_dir_from_config(config_path):
    if not config_path or not config_path.exists():
        return None
    lines = config_path.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#") and line.lstrip("#").strip().lower() == "adr directory":
            for nxt in lines[i + 1:]:
                s = nxt.strip().strip("`")
                if s.startswith("#"):
                    break
                if s and not s.startswith("<!--"):
                    return s.rstrip("/")
    return None


def detect_stack(head_ref, use_worktree, root):
    if use_worktree:
        names = []
        for p in list(root.glob("*")) + list(root.glob("*/*")):
            names.append(p.name)
    else:
        out = git("ls-tree", "-r", "--name-only", head_ref, check=False) or ""
        names = [Path(p).name for p in out.splitlines() if p.count("/") <= 1]
    found = []
    for marker, label in STACK_MARKERS.items():
        if marker in names and label not in found:
            found.append(label)
    if any(n.endswith(".kt") or n.endswith(".kts") for n in names):
        found.insert(0, "Kotlin")
    if any(n.endswith(".tf") for n in names):
        found.append("Terraform")
    return found


def cache_root():
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "team-review"


def config_home():
    """The user's own configuration: model overrides and a personal team-context.md."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "team-review"


REPO_CONTEXT_SOURCES = ["CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md",
                        ".claude/rules", ".claude/team-review.md"]


def repo_context_status(plugin_root, repo_slug, root, base_ref, adr_dir, refresh):
    """The repo layer of the context (ADR index, repo rules, stack), cached per repository and keyed by the git
    hashes of its sources on the base branch, plus the instructions that build it. Any change to one of them, and
    only that, makes the cache stale. Checking costs a few `git rev-parse` calls and no model tokens."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "__", repo_slug or root.name)
    cache_dir = cache_root() / "repos" / name
    sources = {}
    for path in [adr_dir, *REPO_CONTEXT_SOURCES]:
        sources[path] = git("rev-parse", "--verify", "--quiet", f"{base_ref}:{path}", check=False) or None
    builder = plugin_root / "roles" / "repo-context.md"
    h = hashlib.sha256(json.dumps(sources, sort_keys=True).encode())
    if builder.exists():
        h.update(builder.read_bytes())
    key = h.hexdigest()
    manifest = cache_dir / "manifest.json"
    context = cache_dir / "repo-context.md"
    fresh, reason = False, "missing"
    if refresh:
        reason = "refresh requested"
    elif manifest.exists() and context.exists():
        try:
            saved = json.loads(manifest.read_text())
        except json.JSONDecodeError:
            saved = {}
        if saved.get("key") == key:
            fresh, reason = True, "fresh"
        else:
            changed = [p for p in sources if (saved.get("sources") or {}).get(p) != sources[p]]
            reason = ("changed on the base branch: " + ", ".join(changed)) if changed else "builder instructions changed"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return {"cache_dir": str(cache_dir), "cache_path": str(context), "manifest_path": str(manifest),
            "key": key, "base_ref": base_ref, "base_sha": git("rev-parse", base_ref, check=False),
            "sources": sources, "fresh": fresh, "reason": reason}


def find_team_context(root):
    """The team-context file: the repository's own first, then the user's. None when there is neither."""
    for candidate in (root / ".claude" / "team-context.md", config_home() / "team-context.md"):
        if candidate.exists():
            return candidate
    return None


def team_brief_status(plugin_root, root, refresh):
    src = find_team_context(root)
    # One cached brief per source file, so teams that use different files never share a cache entry.
    cache_name = hashlib.sha256(str(src).encode()).hexdigest()[:12] if src else "none"
    cache = cache_root() / "team-briefs" / f"{cache_name}.md"
    # The brief depends on the sources AND on the instructions that build it: a change to either rebuilds it.
    builder = plugin_root / "roles" / "team-brief.md"
    h = hashlib.sha256()
    for f in (src, builder):
        if f and f.exists():
            h.update(f.read_bytes())
    sha = h.hexdigest() if src else None
    fresh, reason = False, "missing"
    if not src:
        reason = "no team-context.md (looked in <repo>/.claude/ and ~/.config/team-review/)"
    elif refresh:
        reason = "refresh requested"
    elif cache.exists():
        first = cache.read_text().splitlines()[0] if cache.stat().st_size else ""
        m = re.search(r"sources-sha256:\s*(\w+)\s+generated:\s*(\S+)", first)
        if not m:
            reason = "cache header missing"
        elif m.group(1) != sha:
            reason = "team-context.md or the team-brief instructions changed"
        else:
            try:
                gen = dt.datetime.fromisoformat(m.group(2).replace("Z", "+00:00").rstrip("-->").strip())
                if gen.tzinfo is None:
                    gen = gen.replace(tzinfo=dt.timezone.utc)
                age = dt.datetime.now(dt.timezone.utc) - gen
                fresh = age.days < CACHE_MAX_AGE_DAYS
                reason = "fresh" if fresh else f"older than {CACHE_MAX_AGE_DAYS} days"
            except ValueError:
                reason = "cache date unreadable"
    cache.parent.mkdir(parents=True, exist_ok=True)
    return {
        "sources_path": str(src) if src else None,
        "sources_exist": src is not None,
        "sources_sha256": sha,
        "cache_path": str(cache),
        "fresh": fresh,
        "reason": reason,
    }


TEST_RE = re.compile(r"(^|/)(test|tests|__tests__|spec|e2e|acceptance)/|\.(spec|test|e2e-spec|steps)\.[cm]?[jt]sx?$|\.feature$|(^|/)src/test/")
DOCS_RE = re.compile(r"\.(md|mdx|rst|txt|adoc)$|(^|/)docs/|(^|/)LICENSE")
CONFIG_RE = re.compile(r"\.(ya?ml|json|toml|ini|env\.example|properties|tf|tfvars|hcl)$|(^|/)Dockerfile|(^|/)\.github/|(^|/)(helm|charts|deploy|k8s)/|(^|/)\.[^/]+rc(\.[a-z]+)?$|lock\.ya?ml$|-lock\.json$|\.lock$")
ALL_ROLES = ["ticket", "architecture", "security", "correctness", "tests"]
AGENTS = ["team-brief", "repo-context", "pr-context", *ALL_ROLES, "judge"]
ALLOWED_MODELS = {"sonnet", "opus", "haiku", "fable"}


def read_models(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text()).get("models", {}) or {}
    except json.JSONDecodeError as e:
        raise UserError(f"{path} is not valid JSON: {e}")


def load_models(plugin_root):
    """Model for every agent: the user's config.json over the plugin's config.default.json; an agent's own entry,
    else 'default', else sonnet."""
    path = config_home() / "config.json"
    cfg = {**read_models(plugin_root / "config.default.json"), **read_models(path)}
    # Older configs had one "context-builder" entry; it now applies to the three context layers.
    legacy = cfg.pop("context-builder", None)
    if legacy:
        for a in ("team-brief", "repo-context", "pr-context"):
            cfg.setdefault(a, legacy)
    unknown = sorted(set(cfg) - set(AGENTS) - {"default"})
    if unknown:
        raise UserError(f"{path}: unknown agent(s) {', '.join(unknown)}. Known: default, {', '.join(AGENTS)}.")
    default = cfg.get("default", "sonnet")
    models = {a: cfg.get(a, default) for a in AGENTS}
    bad = {a: m for a, m in models.items() if m not in ALLOWED_MODELS}
    if bad:
        raise UserError(f"{path}: unsupported model(s) {bad}. Allowed: {', '.join(sorted(ALLOWED_MODELS))}.")
    return models


def file_kind(path, adr_dir):
    if path.startswith(adr_dir.rstrip("/") + "/"):
        return "adr"
    if TEST_RE.search(path):
        return "test"
    if DOCS_RE.search(path):
        return "docs"
    if CONFIG_RE.search(path):
        return "config"
    return "source"


def adaptive_skips(kinds):
    """Roles that have nothing to review for this kind of diff. Overridden by --full or --only."""
    has = {k for k, n in kinds.items() if n}
    skips = {}
    if not has & {"source", "test", "config"}:  # documentation / ADR only
        for r in ("security", "correctness", "tests"):
            skips[r] = "diff changes documentation only"
        if "adr" not in has:
            skips["architecture"] = "diff changes documentation only, no ADR"
    elif not has & {"source", "config"}:  # tests (and docs) only
        for r in ("architecture", "security"):
            skips[r] = "diff changes tests only"
    elif not has & {"source", "test"}:  # config / infrastructure only
        skips["tests"] = "diff changes configuration only"
    return skips


def project_instructions(head_ref, use_worktree, root):
    """Claude/agent instruction files of the reviewed repo: they hold the project's conventions."""
    candidates = ["CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md"]
    if use_worktree:
        found = [c for c in candidates if (root / c).is_file()]
        found += sorted(str(p.relative_to(root)) for p in (root / ".claude" / "rules").glob("**/*.md"))
        return found
    tree = set((git("ls-tree", "-r", "--name-only", head_ref, check=False) or "").splitlines())
    return [c for c in candidates if c in tree] + sorted(t for t in tree if t.startswith(".claude/rules/") and t.endswith(".md"))


RELATED_MAX_FILES_PER_TERM = 12   # a term found in more files than this is too common to be a signal
RELATED_MAX_FILES = 25
RELATED_MAX_TERMS = 40
JIRA_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
STRING_RE = re.compile(r"""(['"`])((?:(?!\1).){12,})\1""")
DECL_RE = re.compile(
    r"\b(?:function|const|let|var|class|interface|type|enum|def|fun|val|object)\s+([A-Za-z_][A-Za-z0-9_]{5,})")
EXPORT_SYMBOL_RE = re.compile(r"\b([A-Z][A-Z0-9_]{5,}|[a-z]+(?:[A-Z][a-z0-9]+){2,})\b")


def related_terms(diff_text):
    """Distinctive terms on the changed lines: ticket keys, string literals, declared and compound names.
    The same rule is often implemented in more than one place; these terms are how to find the other places."""
    terms = {}
    for line in diff_text.splitlines():
        if not line or line[0] not in "+-" or line.startswith(("+++", "---")):
            continue
        body = line[1:]
        for key in JIRA_RE.findall(body):
            terms.setdefault(key, "ticket key")
        for _, text in STRING_RE.findall(body):
            fragment = text.split("${")[0].split("%s")[0].strip()
            if len(fragment) >= 12:
                terms.setdefault(fragment[:60], "string")
        for name in DECL_RE.findall(body):
            terms.setdefault(name, "declared name")
        for name in EXPORT_SYMBOL_RE.findall(body):
            terms.setdefault(name, "name")
    order = {"ticket key": 0, "string": 1, "declared name": 2, "name": 3}
    return sorted(terms.items(), key=lambda kv: order[kv[1]])[:RELATED_MAX_TERMS * 3]


def find_related_code(diff_text, head_sha, changed, adr_dir, ignore):
    """Files OUTSIDE the diff that contain the diff's distinctive terms, with the matching lines."""
    hits, used = {}, 0
    for term, kind in related_terms(diff_text):
        if used >= RELATED_MAX_TERMS:
            break
        out = run(["git", "grep", "-n", "-I", "-F", "-e", term, head_sha, "--", "."], check=False)
        if not out:
            continue
        per_file = {}
        for row in out.splitlines():
            parts = row.split(":", 3)  # sha:path:line:text
            if len(parts) < 4:
                continue
            _, path, lineno, text = parts
            if path in changed or file_kind(path, adr_dir) in ("docs", "adr"):
                continue
            if any(Path(path).match(g) for g in ignore):
                continue
            per_file.setdefault(path, []).append({"line": int(lineno), "text": text.strip()[:200]})
        if not per_file or len(per_file) > RELATED_MAX_FILES_PER_TERM:
            continue
        used += 1
        for path, lines in per_file.items():
            entry = hits.setdefault(path, {"file": path, "kind": file_kind(path, adr_dir), "terms": [], "lines": []})
            entry["terms"].append({"term": term, "type": kind})
            for l in lines[:3]:
                if l not in entry["lines"]:
                    entry["lines"].append(l)
    ranked = sorted(hits.values(), key=lambda e: (e["kind"] != "source", -len(e["terms"]), e["file"]))
    for e in ranked:
        e["lines"] = sorted(e["lines"], key=lambda l: l["line"])[:6]
    return ranked[:RELATED_MAX_FILES]


SCRUTINISE_RE = re.compile(r"^\s*(?:#{1,6}\s*|\*\*)\s*anything to scrutini[sz]e\??\s*(?:\*\*)?\s*$", re.I)
HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S")
TEMPLATE_HINTS = ("risks, rollback plan, or areas to focus review on",)
EMPTY_ITEMS = {"", "-", "none", "n/a", "na", "nothing", "no", "nope", "none.", "n/a."}
FOCUS_MAX_ITEMS = 10
FOCUS_MAX_CHARS = 500


def scrutinise_items(body):
    """The points of the PR description's "Anything to scrutinise?" section (from the team's PR template).
    Bullets become one item each; without bullets, each paragraph is one item. Template hints and empty
    placeholders are dropped."""
    lines = (body or "").replace("\r\n", "\n").splitlines()
    start = next((i for i, l in enumerate(lines) if SCRUTINISE_RE.match(l)), None)
    if start is None:
        return []
    section = []
    for line in lines[start + 1:]:
        if HEADING_RE.match(line) or SCRUTINISE_RE.match(line):
            break
        section.append(line)
    text = re.sub(r"<!--.*?-->", "", "\n".join(section), flags=re.S)
    items, current = [], None
    for line in text.splitlines():
        bullet = re.match(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+(.*)$", line)
        if bullet:
            if current is not None:
                items.append(current)
            current = bullet.group(1)
        elif line.strip() and current is not None and (line.startswith((" ", "\t")) or not items and current):
            current += " " + line.strip()
        elif not line.strip():
            if current is not None:
                items.append(current)
                current = None
        else:
            current = line.strip() if current is None else current + " " + line.strip()
    if current is not None:
        items.append(current)
    clean = []
    for item in items:
        item = " ".join(item.split())
        if item.lower().strip(" .") in EMPTY_ITEMS or any(h in item.lower() for h in TEMPLATE_HINTS):
            continue
        clean.append(item[:FOCUS_MAX_CHARS] + (" …" if len(item) > FOCUS_MAX_CHARS else ""))
    return clean


def build_focus(flag_items, pr_body):
    """Focus items: the reviewer's own (--focus) first, then the author's (PR description). They add depth to the
    review and never narrow it."""
    focus = []
    for text in flag_items or []:
        if text and text.strip():
            focus.append({"text": " ".join(text.split())[:FOCUS_MAX_CHARS], "source": "flag"})
    for text in scrutinise_items(pr_body):
        focus.append({"text": text, "source": "pr description"})
    for i, f in enumerate(focus[:FOCUS_MAX_ITEMS], 1):
        f["id"] = f"F{i}"
    return focus[:FOCUS_MAX_ITEMS], max(0, len(focus) - FOCUS_MAX_ITEMS)


TAG_RE = re.compile(r"team-review · (R\d+)")


def gh_paged(path):
    out = run(["gh", "api", "--paginate", "--slurp", path], check=False) if gh_available() else None
    if not out:
        return None
    try:
        pages = json.loads(out)
    except json.JSONDecodeError:
        return None
    return [item for page in pages for item in (page if isinstance(page, list) else [page])]


def fetch_pr_comments(repo_slug, number):
    """Existing discussion on the PR, so the review does not repeat it and knows what was already posted."""
    repo = repo_slug or "{owner}/{repo}"

    def short(body):
        body = (body or "").strip()
        return body if len(body) <= 1500 else body[:1500] + " …[truncated]"

    def tag(body):
        m = TAG_RE.search(body or "")
        return m.group(1) if m else None

    inline = gh_paged(f"repos/{repo}/pulls/{number}/comments")
    general = gh_paged(f"repos/{repo}/issues/{number}/comments")
    reviews = gh_paged(f"repos/{repo}/pulls/{number}/reviews")
    if inline is None and general is None and reviews is None:
        return None
    return {
        "inline": [{"id": c["id"], "author": (c.get("user") or {}).get("login"), "path": c.get("path"),
                    "line": c.get("line") or c.get("original_line"), "outdated": c.get("line") is None,
                    "in_reply_to": c.get("in_reply_to_id"), "url": c.get("html_url"),
                    "team_review_id": tag(c.get("body")), "body": short(c.get("body"))} for c in inline or []],
        "general": [{"id": c["id"], "author": (c.get("user") or {}).get("login"), "url": c.get("html_url"),
                     "team_review_id": tag(c.get("body")), "body": short(c.get("body"))} for c in general or []],
        "reviews": [{"id": r["id"], "author": (r.get("user") or {}).get("login"), "state": r.get("state"),
                     "url": r.get("html_url"), "body": short(r.get("body"))} for r in reviews or [] if (r.get("body") or "").strip()],
    }


def default_base():
    info = gh_json(["repo", "view", "--json", "defaultBranchRef"])
    if info and info.get("defaultBranchRef"):
        return info["defaultBranchRef"]["name"]
    sym = git("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", check=False)
    if sym:
        return sym.rsplit("/", 1)[-1]
    return next((b for b in ("main", "master") if ref_ok(f"refs/heads/{b}")), None)


def repo_slug_of():
    remote_url = git("remote", "get-url", "origin", check=False)
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", remote_url or "")
    return m.group(1) if m else None


def context_only(args, plugin_root, models):
    """For /team-review:context: the status of the team and repo caches, without a review run."""
    if git("rev-parse", "--is-inside-work-tree", check=False) != "true":
        raise UserError("Not inside a git repository. Run it from the project folder.")
    root = Path(git("rev-parse", "--show-toplevel"))
    os.chdir(root)
    base = default_base()
    if not base:
        raise UserError("Could not determine the default branch.")
    if git("remote", "get-url", "origin", check=False) is not None:
        git("fetch", "--quiet", "origin", base, check=False)
    base_ref = f"refs/remotes/origin/{base}" if ref_ok(f"refs/remotes/origin/{base}") else f"refs/heads/{base}"
    repo_config = root / ".claude" / "team-review.md"
    adr_dir = adr_dir_from_config(repo_config) or "docs/adrs"
    slug = repo_slug_of()
    out = {
        "repo_root": str(root), "repo": slug, "base": base, "base_ref": base_ref, "adr_dir": adr_dir,
        "repo_config": str(repo_config) if repo_config.exists() else None,
        "detected_stack": detect_stack(base_ref, False, root),
        "models": models,
        "team_brief": team_brief_status(plugin_root, root, args.refresh_context or args.refresh_team),
        "repo_context": repo_context_status(plugin_root, slug, root, base_ref, adr_dir,
                                            args.refresh_context or args.refresh_repo),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin-root", required=True)
    ap.add_argument("--target", default="")
    ap.add_argument("--uncommitted", action="store_true")
    ap.add_argument("--refresh-context", action="store_true", help="rebuild both the team and the repo cache")
    ap.add_argument("--refresh-team", action="store_true", help="rebuild the team brief")
    ap.add_argument("--refresh-repo", action="store_true", help="rebuild the repo context")
    ap.add_argument("--context-only", action="store_true", help="only report the cache status (no review run)")
    ap.add_argument("--full", action="store_true", help="disable adaptive role skipping")
    ap.add_argument("--focus", action="append", default=[], help="a point to examine in depth (repeatable)")
    ap.add_argument("--no-pr-focus", action="store_true", help="ignore the PR description's 'Anything to scrutinise?'")
    args = ap.parse_args()

    plugin_root = Path(args.plugin_root).expanduser().resolve()
    warnings = []
    models = load_models(plugin_root)
    if args.context_only:
        return context_only(args, plugin_root, models)

    if git("rev-parse", "--is-inside-work-tree", check=False) != "true":
        raise UserError("Not inside a git repository. Run the review from the project folder.")
    root = Path(git("rev-parse", "--show-toplevel"))
    os.chdir(root)

    current = git("rev-parse", "--abbrev-ref", "HEAD")
    kind, value = parse_target(args.target.strip())
    has_origin = git("remote", "get-url", "origin", check=False) is not None
    pr = None

    # ---- resolve head -------------------------------------------------------
    if kind == "pr":
        pr = gh_json(["pr", "view", str(value), "--json", PR_FIELDS])
        if not pr:
            raise UserError(f"Could not read PR #{value} with gh (is gh installed and authenticated, and is this the right repo?).")
        branch = pr["headRefName"]
        if not pr.get("isCrossRepository") and ref_ok(f"refs/heads/{branch}"):
            head_ref = f"refs/heads/{branch}"
            local_sha = git("rev-parse", head_ref)
            if local_sha != pr["headRefOid"]:
                warnings.append(f"Local branch {branch} ({local_sha[:8]}) differs from the PR head ({pr['headRefOid'][:8]}); reviewing the LOCAL branch.")
        else:
            pr_ref = f"refs/team-review/pr-{value}"
            git("fetch", "--quiet", "origin", f"+refs/pull/{value}/head:{pr_ref}")
            head_ref = pr_ref
    else:
        branch = current if kind == "current" else value
        if branch == "HEAD":
            raise UserError("Detached HEAD: pass a branch name or PR number.")
        if ref_ok(f"refs/heads/{branch}"):
            head_ref = f"refs/heads/{branch}"
        else:
            if has_origin:
                git("fetch", "--quiet", "origin", branch, check=False)
            if ref_ok(f"refs/remotes/origin/{branch}"):
                head_ref = f"refs/remotes/origin/{branch}"
                warnings.append(f"No local branch {branch}; reviewing origin/{branch}.")
            else:
                raise UserError(f"Branch '{branch}' not found locally or on origin.")
        pr = gh_json(["pr", "view", branch, "--json", PR_FIELDS])
        if pr and pr.get("state") != "OPEN":
            warnings.append(f"PR #{pr['number']} for this branch is {pr['state']}.")

    head_sha = git("rev-parse", head_ref)

    # ---- resolve base -------------------------------------------------------
    if pr:
        base = pr["baseRefName"]
    else:
        base = None
        info = gh_json(["repo", "view", "--json", "defaultBranchRef"])
        if info and info.get("defaultBranchRef"):
            base = info["defaultBranchRef"]["name"]
        if not base:
            sym = git("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", check=False)
            base = sym.rsplit("/", 1)[-1] if sym else None
        if not base:
            base = next((b for b in ("main", "master") if ref_ok(f"refs/heads/{b}")), None)
        if not base:
            raise UserError("Could not determine the base branch.")
        warnings.append(f"No PR found for {branch}; reviewing against the default branch {base}.")
    if has_origin:
        if git("fetch", "--quiet", "origin", base, check=False) is None:
            warnings.append(f"Could not fetch origin/{base}; using the last known version.")
    base_ref = f"refs/remotes/origin/{base}" if ref_ok(f"refs/remotes/origin/{base}") else f"refs/heads/{base}"
    if not ref_ok(base_ref):
        raise UserError(f"Base branch '{base}' not found.")

    merge_base = git("merge-base", base_ref, head_ref, check=False)
    if not merge_base:
        raise UserError(f"No common ancestor between {base} and {branch}.")

    # ---- repo config, pathspecs ---------------------------------------------
    repo_config = root / ".claude" / "team-review.md"
    ignore = read_ignore_paths(repo_config)
    pathspec = ["--", "."] + [f":(exclude,glob){p}" for p in ignore] if ignore else []

    # ---- diff ---------------------------------------------------------------
    dirty_out = git("status", "--porcelain", "--untracked-files=no", check=False) or ""
    dirty = bool(dirty_out.strip()) and branch == current
    include_wt = args.uncommitted and branch == current
    if args.uncommitted and branch != current:
        warnings.append("--uncommitted ignored: the target is not the current branch.")
    diff_range = [merge_base] if include_wt else [merge_base, head_ref]
    # Agents may read the working tree only when it matches what is reviewed.
    reads_from_worktree = head_ref == f"refs/heads/{current}" and (include_wt or not dirty)

    diff = run(["git", "diff", "--no-color", "--no-ext-diff", "-U10", "-M", *diff_range, *pathspec])
    numstat = run(["git", "diff", "--numstat", "-M", *diff_range, *pathspec])
    name_status = run(["git", "diff", "--name-status", "-M", *diff_range, *pathspec])

    files, adds, dels = [], 0, 0
    status_by_path = {}
    for line in name_status.splitlines():
        parts = line.split("\t")
        status_by_path[parts[-1]] = parts[0][0]
    for line in numstat.splitlines():
        a, d, path = line.split("\t", 2)
        if " => " in path:
            path = re.sub(r"\{([^}]*) => ([^}]*)\}", r"\2", path)
            path = path.split(" => ")[-1]
        a_i = int(a) if a.isdigit() else 0
        d_i = int(d) if d.isdigit() else 0
        adds += a_i
        dels += d_i
        files.append({"path": path, "status": status_by_path.get(path, "M"),
                      "additions": a_i, "deletions": d_i, "binary": a == "-"})

    commits = (git("log", "--no-merges", "--format=%h %s", f"{merge_base}..{head_ref}", check=False) or "").splitlines()

    # ---- ADRs, stack, team brief --------------------------------------------
    adr_dir = adr_dir_from_config(repo_config) or "docs/adrs"
    if reads_from_worktree:
        adr_exists = (root / adr_dir).is_dir()
    else:
        adr_exists = bool(git("ls-tree", "--name-only", head_ref, f"{adr_dir}/", check=False))

    # ---- run dir --------------------------------------------------------------
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir", check=False) or str(root / ".git")
    safe_branch = re.sub(r"[^A-Za-z0-9._-]+", "_", branch)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    branch_dir = Path(common) / "team-review" / safe_branch
    run_dir = branch_dir / stamp
    (run_dir / "findings").mkdir(parents=True, exist_ok=True)

    remote_url = git("remote", "get-url", "origin", check=False)
    repo_slug = None
    if remote_url:
        m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", remote_url)
        repo_slug = m.group(1) if m else None

    kinds = {k: 0 for k in ("source", "test", "config", "docs", "adr")}
    for f in files:
        f["kind"] = file_kind(f["path"], adr_dir)
        kinds[f["kind"]] += 1
    auto_skip = {} if args.full else adaptive_skips(kinds)

    focus, focus_dropped = build_focus(args.focus, None if args.no_pr_focus or not pr else pr.get("body"))
    if focus_dropped:
        warnings.append(f"{focus_dropped} focus item(s) beyond the first {FOCUS_MAX_ITEMS} were left out.")
    if focus and "correctness" in auto_skip:
        # A focus item must always have a role that examines it.
        del auto_skip["correctness"]

    related = find_related_code(diff, head_sha, {f["path"] for f in files}, adr_dir, ignore)
    (run_dir / "related_code.json").write_text(json.dumps(related, indent=2, ensure_ascii=False))

    pr_comments = fetch_pr_comments(repo_slug, pr["number"]) if pr else None
    if pr and pr_comments is None:
        warnings.append("Could not read the existing PR comments; the review may repeat points already raised.")
    if pr_comments is not None:
        (run_dir / "pr_comments.json").write_text(json.dumps(pr_comments, indent=2, ensure_ascii=False))

    rule_paths = (adr_dir.rstrip("/") + "/", *REPO_CONTEXT_SOURCES)
    context_changes = [f["path"] for f in files
                       if any(f["path"] == r or f["path"].startswith(r.rstrip("/") + "/") for r in rule_paths)]

    diff_lines = diff.count("\n")
    if diff_lines > LARGE_DIFF_LINES:
        warnings.append(f"Large diff ({diff_lines} lines): reviewers will read it file by file; consider reviewing in parts with --only.")

    meta = {
        "repo_root": str(root),
        "repo": repo_slug,
        "target": {"kind": kind, "value": value},
        "branch": branch,
        "current_branch": current,
        "head_ref": head_ref,
        "head_sha": head_sha,
        "base": base,
        "base_ref": base_ref,
        "merge_base": merge_base,
        "reads_from_worktree": bool(reads_from_worktree),
        "includes_uncommitted": include_wt,
        "dirty": dirty,
        "pr": None if not pr else {
            "number": pr["number"], "url": pr["url"], "title": pr["title"], "body": pr.get("body") or "",
            "state": pr.get("state"), "draft": pr.get("isDraft"),
            "author": (pr.get("author") or {}).get("login"), "head_sha": pr["headRefOid"],
        },
        "jira_key": jira_key(branch),
        "stats": {"files": len(files), "additions": adds, "deletions": dels, "diff_lines": diff_lines},
        "files": files,
        "commits": commits[:50],
        "ignored_paths": ignore,
        "repo_config": str(repo_config) if repo_config.exists() else None,
        "adr_dir": adr_dir,
        "adr_dir_exists": adr_exists,
        "detected_stack": detect_stack(head_ref, reads_from_worktree, root),
        "project_instructions": project_instructions(head_ref, reads_from_worktree, root),
        "file_kinds": kinds,
        "focus": focus,
        "models": models,
        "related_code": {"path": str(run_dir / "related_code.json"), "files": len(related)},
        "auto_skip": [{"role": r, "reason": why} for r, why in auto_skip.items()],
        "pr_comments": None if pr_comments is None else {
            "path": str(run_dir / "pr_comments.json"),
            "inline": len(pr_comments["inline"]), "general": len(pr_comments["general"]),
            "reviews": len(pr_comments["reviews"]),
            "team_review_posted": sorted({c["team_review_id"] for c in pr_comments["inline"] + pr_comments["general"] if c["team_review_id"]}),
        },
        "team_brief": team_brief_status(plugin_root, root, args.refresh_context or args.refresh_team),
        "repo_context": repo_context_status(plugin_root, repo_slug, root, base_ref, adr_dir,
                                            args.refresh_context or args.refresh_repo),
        "pr_changes_context": context_changes,
        "ticket_path": str(run_dir / "ticket.json"),
        "diff_empty": not diff.strip(),
        "run_dir": str(run_dir),
        "branch_dir": str(branch_dir),
        "warnings": warnings,
    }
    (run_dir / "diff.patch").write_text(diff)
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(json.dumps(meta, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except UserError as e:
        print(f"team-review: {e}", file=sys.stderr)
        sys.exit(1)
