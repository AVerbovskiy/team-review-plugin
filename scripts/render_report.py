#!/usr/bin/env python3
"""team-review: render review.json as a markdown report (en or bg)."""
import argparse
import json
import sys
from pathlib import Path

SEV_ORDER = ["blocker", "major", "question", "minor", "nit"]
SEV_ICON = {"blocker": "🔴", "major": "🟠", "question": "❓", "minor": "🟡", "nit": "🔵"}

L = {
    "en": {
        "review": "Review", "ticket": "Ticket", "unavailable": "unavailable",
        "what": "What this PR does", "risk": "Risk surface", "verdict": "Verdict",
        "sev": {"blocker": "Blocker", "major": "Major", "question": "Question", "minor": "Minor", "nit": "Nit"},
        "conf": {"high": "high", "medium": "medium", "low": "low"},
        "verdicts": {
            "changes_required": "⛔ Changes required",
            "needs_discussion": "⚠️ Needs discussion",
            "approve_with_comments": "✅ Approve with comments",
            "ready": "✅ Ready to merge",
        },
        "hidden": "hidden: {n} (nits / low confidence; use --all)",
        "cols": ["#", "Sev", "Role", "Where", "Problem"],
        "problem": "Problem", "why": "Why it matters", "suggestion": "Suggestion",
        "current": "Current code", "fix": "Example fix",
        "confidence": "confidence", "pre_existing": "pre-existing", "pr_level": "PR-level",
        "posted": "posted", "ac": "Acceptance criteria coverage",
        "focus": "Focus areas", "focus_cols": ["#", "Focus", "Source", "Result"],
        "focus_status": {"issue": "⚠️ issue: {ids}", "no_issue": "✅ checked, no issue", "not_checked": "➖ not checked"},
        "focus_source": {"flag": "you", "pr description": "PR description"},
        "ac_status": {"implemented": "✅ implemented", "partial": "🟡 partial", "missing": "🔴 missing", "unverifiable": "➖ not verifiable"},
        "no_findings": "No findings. 🎉",
        "footer": "Roles: {run}. Skipped: {skipped}. Rejected by the judge as false positives / out of scope: {rej}.",
        "none": "none", "files": "files", "draft": "draft", "uncommitted": "includes uncommitted changes", "fixed": "local fix",
    },
    "bg": {
        "review": "Ревю", "ticket": "Тикет", "unavailable": "недостъпен",
        "what": "Какво прави PR-ът", "risk": "Рискови зони", "verdict": "Вердикт",
        "sev": {"blocker": "Блокер", "major": "Сериозен", "question": "Въпрос", "minor": "Дребен", "nit": "Nit"},
        "conf": {"high": "висока", "medium": "средна", "low": "ниска"},
        "verdicts": {
            "changes_required": "⛔ Нужни са промени",
            "needs_discussion": "⚠️ Нужно е обсъждане",
            "approve_with_comments": "✅ Одобрен с коментари",
            "ready": "✅ Готов за merge",
        },
        "hidden": "скрити: {n} (nits / ниска увереност; ползвай --all)",
        "cols": ["#", "Ниво", "Роля", "Къде", "Проблем"],
        "problem": "Проблем", "why": "Защо е важно", "suggestion": "Предложение",
        "current": "Текущ код", "fix": "Примерна поправка",
        "confidence": "увереност", "pre_existing": "съществуващ отпреди", "pr_level": "целия PR",
        "posted": "публикуван", "ac": "Покритие на acceptance criteria",
        "focus": "Фокус на ревюто", "focus_cols": ["#", "Фокус", "Източник", "Резултат"],
        "focus_status": {"issue": "⚠️ проблем: {ids}", "no_issue": "✅ проверено, няма проблем", "not_checked": "➖ не е проверено"},
        "focus_source": {"flag": "ти", "pr description": "описанието на PR-а"},
        "ac_status": {"implemented": "✅ имплементиран", "partial": "🟡 частично", "missing": "🔴 липсва", "unverifiable": "➖ не може да се провери"},
        "no_findings": "Няма намерени проблеми. 🎉",
        "footer": "Роли: {run}. Пропуснати: {skipped}. Отхвърлени от съдията (фалшиви / извън обхвата): {rej}.",
        "none": "няма", "files": "файла", "draft": "чернова (draft)", "uncommitted": "включва некомитнати промени", "fixed": "локална поправка",
    },
}

LANG_BY_EXT = {
    "ts": "ts", "tsx": "tsx", "js": "js", "mjs": "js", "cjs": "js", "jsx": "jsx", "kt": "kotlin", "kts": "kotlin",
    "java": "java", "py": "python", "go": "go", "rs": "rust", "sql": "sql", "yaml": "yaml", "yml": "yaml",
    "json": "json", "md": "markdown", "sh": "bash", "tf": "hcl", "feature": "gherkin", "sqlx": "sql",
}


def fence_lang(path):
    return LANG_BY_EXT.get(Path(path or "").suffix.lstrip(".").lower(), "")


def excerpt_caption(ex):
    if not ex.get("file"):
        return None
    rng = ex.get("start_line")
    if rng and ex.get("end_line") and ex["end_line"] != rng:
        rng = f"{rng}-{ex['end_line']}"
    name = f"{ex['file']}:{rng}" if rng else ex["file"]
    target = f"{ex['file']}:{ex['start_line']}" if ex.get("start_line") else ex["file"]
    return f"[{name}]({target})"


def code_block(code, lang, caption=None):
    code = (code or "").rstrip("\n")
    fence = "````" if "```" in code else "```"
    head = f"{caption}\n" if caption else ""
    return f"{head}{fence}{lang}\n{code}\n{fence}\n"


def tr(obj, lang, key):
    if lang != "en":
        v = (obj.get("i18n") or {}).get(lang, {}).get(key)
        if v:
            return v
    return obj.get(key)


def loc(f, t):
    if not f.get("file"):
        return t["pr_level"]
    if f.get("line"):
        ref = f"{f['file']}:{f['line']}"
        name = f"{Path(f['file']).name}:{f['line']}"
        if f.get("end_line") and f["end_line"] != f["line"]:
            name += f"-{f['end_line']}"
        return f"[{name}]({ref})"
    return f"[{Path(f['file']).name}]({f['file']})"


def cell(s):
    return (s or "").replace("|", "\\|").replace("\n", " ")


def visible(f, show_all):
    return show_all or (f["severity"] != "nit" and f.get("confidence") != "low")


def render(review, lang, show_all):
    t = L[lang]
    meta, summary, ticket = review.get("meta", {}), review.get("summary", {}), review.get("ticket") or {}
    findings = sorted(review.get("findings", []),
                      key=lambda f: SEV_ORDER.index(f["severity"]) if f["severity"] in SEV_ORDER else 9)
    shown = [f for f in findings if visible(f, show_all)]
    hidden = len(findings) - len(shown)
    out = []

    pr = meta.get("pr")
    pr_txt = ""
    if pr:
        pr_txt = f" ([PR #{pr['number']}]({pr['url']}))" if pr.get("url") else f" (PR #{pr['number']})"
    if pr and pr.get("draft"):
        pr_txt += f" · 📝 {t['draft']}"
    if meta.get("includes_uncommitted"):
        pr_txt += f" · ⚠️ {t['uncommitted']}"
    stats = meta.get("stats", {})
    out.append(f"## {t['review']}: `{meta.get('branch')}` → `{meta.get('base')}`{pr_txt}")
    line2 = f"`{(meta.get('head_sha') or '')[:8]}` · {stats.get('files', '?')} {t['files']}, +{stats.get('additions', 0)}/−{stats.get('deletions', 0)}"
    if ticket.get("key"):
        if ticket.get("available", True) and ticket.get("title"):
            tk = f"[{ticket['key']}]({ticket['url']})" if ticket.get("url") else ticket["key"]
            line2 += f" · {t['ticket']} {tk}: {ticket['title']}"
        else:
            line2 += f" · {t['ticket']} {ticket['key']} ({t['unavailable']})"
    out.append(line2)
    out.append("")

    out.append(f"### {t['what']}")
    for b in tr(summary, lang, "what_it_does") or []:
        out.append(f"- {b}")
    risk = tr(summary, lang, "risk_surface")
    if risk:
        out.append(f"\n**{t['risk']}:** {risk}")
    out.append("")

    counts = {s: sum(1 for f in shown if f["severity"] == s) for s in SEV_ORDER}
    count_txt = " · ".join(f"{counts[s]} {SEV_ICON[s]}" for s in SEV_ORDER if counts[s])
    verdict = t["verdicts"].get(summary.get("verdict"), summary.get("verdict", ""))
    out.append(f"### {t['verdict']}: {verdict}" + (f" · {count_txt}" if count_txt else ""))
    reason = tr(summary, lang, "verdict_reason")
    if reason:
        out.append(reason)
    if hidden:
        out.append(f"_{t['hidden'].format(n=hidden)}_")
    out.append("")

    focus = review.get("focus_results") or []
    if focus:
        out.append(f"### {t['focus']}\n")
        out.append("| " + " | ".join(t["focus_cols"]) + " |")
        out.append("|---|---|---|---|")
        for fr in focus:
            ids = ", ".join(f"**{i}**" for i in fr.get("finding_ids") or []) or "—"
            status = t["focus_status"].get(fr.get("status"), fr.get("status", "")).replace("{ids}", ids)
            text = fr.get("text") or ""
            short = text if len(text) <= 140 else text.replace("**", "")[:137] + "…"
            conclusion = tr(fr, lang, "conclusion") or ""
            evidence = f" ({fr['evidence']})" if fr.get("evidence") else ""
            out.append(f"| **{fr.get('id')}** | {cell(short)} | {t['focus_source'].get(fr.get('source'), fr.get('source', ''))} "
                       f"| {status}<br>{cell(conclusion)}{cell(evidence)} |")
        out.append("")

    ac = ticket.get("ac_coverage") or []
    if ac:
        out.append(f"**{t['ac']}**\n")
        out.append("| AC | | |")
        out.append("|---|---|---|")
        for a in ac:
            out.append(f"| {cell(str(a.get('ac')))}. {cell(a.get('text'))} | {t['ac_status'].get(a.get('status'), a.get('status'))} | {cell(a.get('where'))} |")
        out.append("")

    if not shown:
        out.append(t["no_findings"])
    else:
        out.append("| " + " | ".join(t["cols"]) + " |")
        out.append("|---|---|---|---|---|")
        for f in shown:
            posted = (" 📤" if f.get("posted") else "") + (" 🛠️" if (f.get("fix") or {}).get("status") == "fixed" else "")
            out.append(f"| **{f['id']}**{posted} | {SEV_ICON.get(f['severity'], '')} | {cell(', '.join(f.get('roles', [])))} | {loc(f, t)} | {cell(tr(f, lang, 'title'))} |")
        out.append("")
        for f in shown:
            sev = f["severity"]
            head = f"#### {SEV_ICON.get(sev, '')} {f['id']} · {t['sev'].get(sev, sev)} · {', '.join(f.get('roles', []))} · {loc(f, t)}"
            out.append(head)
            tags = [f"{t['confidence']}: {t['conf'].get(f.get('confidence'), f.get('confidence'))}"]
            if f.get("category"):
                tags.append(f["category"])
            if f.get("pre_existing"):
                tags.append(t["pre_existing"])
            fix = f.get("fix") or {}
            if fix.get("status"):
                tags.append(f"{t['fixed']}: {fix['status']}" + (f" ({fix['note']})" if fix.get("note") else ""))
            if f.get("posted"):
                p = f["posted"]
                tags.append(f"{t['posted']}: {p.get('url', '') if isinstance(p, dict) else p}")
            out.append(f"**{tr(f, lang, 'title')}** _({' · '.join(tags)})_\n")
            out.append(f"**{t['problem']}:** {tr(f, lang, 'problem')}\n")
            excerpts = f.get("code_excerpts") or []
            if excerpts:
                out.append(f"**{t['current']}:**\n")
                for ex in excerpts:
                    out.append(code_block(ex.get("code"), fence_lang(ex.get("file")), excerpt_caption(ex)))
            out.append(f"**{t['why']}:** {tr(f, lang, 'why')}\n")
            if tr(f, lang, "suggestion"):
                out.append(f"**{t['suggestion']}:** {tr(f, lang, 'suggestion')}\n")
            fixes = f.get("fix_example") or []
            if fixes:
                out.append(f"**{t['fix']}:**\n")
                for fx in fixes:
                    out.append(code_block(fx.get("code"), fx.get("language") or fence_lang(fx.get("file")),
                                          f"`{fx['file']}`" if fx.get("file") else None))
            elif f.get("suggestion_code"):
                out.append(f"**{t['fix']}:**\n")
                out.append(code_block(f["suggestion_code"], fence_lang(f.get("file")), loc(f, t)))

    skipped = ", ".join(f"{s['role']} ({s.get('reason', '')})" for s in review.get("roles_skipped", [])) or t["none"]
    out.append("---")
    out.append("_" + t["footer"].format(run=", ".join(review.get("roles_run", [])) or t["none"],
                                       skipped=skipped, rej=len(review.get("rejected", []))) + "_")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("review")
    ap.add_argument("--lang", default="en", choices=sorted(L))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--set-latest", action="store_true",
                    help="point <branch_dir>/latest at this run; done only once the review is complete")
    a = ap.parse_args()
    review = json.loads(Path(a.review).read_text())
    md = render(review, a.lang, a.all)
    if a.out:
        Path(a.out).write_text(md)
    if a.set_latest:
        run_dir = Path(a.review).resolve().parent
        latest = run_dir.parent / "latest"
        tmp = run_dir.parent / ".latest.tmp"
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()
        tmp.symlink_to(run_dir.name)
        tmp.replace(latest)  # atomic swap: latest never points at an unfinished run
    sys.stdout.write(md)


if __name__ == "__main__":
    main()
