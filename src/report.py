"""Generate advisory reports and reconcile marker-owned GitHub artefacts."""

import html
import re


START = "<!-- handover-nanny:{name}:start -->"
END = "<!-- handover-nanny:{name}:end -->"
BOT = "github-actions[bot]"
QUESTIONS = """### HANDOVER STATUS

Please add a separate comment answering these questions (do not edit this generated comment):

Intended purpose:
Current state: COMPLETE / PARTIAL / BROKEN / EXPERIMENTAL / SUPERSEDED / UNKNOWN
Why was this not merged?
What useful work would be lost if this branch were ignored?
Recommended action for the next team:
Known problems:
Missing tests:
Anything else the next team needs to know:"""


def safe(value):
    return html.escape(str(value)).replace("`", "&#96;").replace("\n", " ")


def section(name, body):
    return f"{START.format(name=name)}\n{body}\n{END.format(name=name)}"


def replace_section(original, name, body):
    start, end = START.format(name=name), END.format(name=name)
    new = section(name, body)
    if start in original and end in original and original.index(start) < original.index(end):
        return original[:original.index(start)] + new + original[original.index(end) + len(end):]
    return original.rstrip() + ("\n\n" if original.strip() else "") + new


def evidence(branch, default):
    relationship = (f"{branch.ahead} commits ahead and {branch.behind} behind; "
                    f"merge base `{branch.base[:12]}`; "
                    f"{'merged' if branch.merged else 'not merged'} into `{safe(default)}`"
                    if branch.base else "no common ancestor found; relationship unknown")
    commits = "\n".join(f"- {safe(c)}" for c in branch.commits[:30]) or "- None identified"
    files = "\n".join(f"- `{safe(f)}`" for f in branch.files[:50]) or "- None identified"
    if len(branch.commits) > 30:
        commits += f"\n- ... {len(branch.commits) - 30} more"
    if len(branch.files) > 50:
        files += f"\n- ... {len(branch.files) - 50} more"
    return (f"**FACT:** Branch `{safe(branch.name)}`: {relationship}. "
            f"Latest commit: {safe(branch.recent)}. Unique merge commits: {branch.unique_merges}.\n\n"
            f"**FACT:** Patch-unique non-merge commits:\n{commits}\n\n"
            f"**FACT:** Files changed since merge base (may include merged work):\n{files}\n\n"
            f"**HEURISTIC:** {branch.classification}; unique changes or topology may need human review.\n\n"
            "**UNKNOWN:** Intent, completeness, correctness and whether this work should be integrated.")


def human_statements(comments):
    return [c.get("body", "") for c in comments
            if c.get("user", {}).get("type") != "Bot"
            and "<!-- handover-nanny:" not in c.get("body", "")
            and re.search(r"\bHANDOVER STATUS\b", c.get("body", ""), re.I)]


def start_text(branch, default, comments, pr):
    statements = human_statements(comments)
    quoted = "\n".join("> " + safe(line) for statement in statements
                       for line in statement[:4000].splitlines())
    human = quoted if quoted else "No structured outgoing-team statement found."
    state = ", ".join(sorted(set(re.findall(
        r"(?im)^\s*current state:\s*(COMPLETE|PARTIAL|BROKEN|EXPERIMENTAL|SUPERSEDED|UNKNOWN)\b",
        "\n".join(statements)))))
    consistency = ("The stated state cannot be verified from Git topology alone."
                   if state else "No comparable structured state was found.")
    if state and "SUPERSEDED" in state and branch.commits:
        consistency = "A SUPERSEDED statement coexists with patch-unique commits; investigate the discrepancy."
    pr_state = f"PR is {safe(pr.get('state', 'unknown'))}." if pr else "No associated PR was found."
    return (f"## START MODE\n\n{evidence(branch, default)}\n\n"
            f"**FACT:** {pr_state}\n\n**HUMAN STATEMENT (unverified):**\n{human}\n\n"
            f"**HEURISTIC:** {consistency}\n\n"
            "**UNKNOWN:** Ignoring may lose useful work; integrating may introduce unfinished or conflicting changes. "
            "Ask a maintainer whether to integrate, preserve, or discard the work after reviewing it.")


def reconcile_comment(api, dry_run, number, name, body, comments):
    marker = START.format(name=name)
    existing = next((c for c in comments if marker in c.get("body", "")
                     and c.get("user", {}).get("login") == BOT), None)
    text = replace_section(existing.get("body", "") if existing else "", name, body)
    action = "update" if existing else "create"
    print(f"Would {action} {name} comment on PR #{number}" if dry_run else
          f"{action.capitalize()} {name} comment on PR #{number}")
    if not dry_run:
        if existing:
            if text != existing.get("body", ""):
                api.update_comment(existing["id"], text)
        else:
            api.create_comment(number, text)


def run(mode, default, head, boundary, branches, api=None, dry_run=False, repository=None):
    pulls = api.pulls(default) if api else []
    issues = api.issues() if api else []
    if not api:
        print("GitHub data unavailable: PRs, comments and issue existence are unknown.")
    print(f"FACT: {default} HEAD {head}")
    print("HEURISTIC: Settled boundary " + (boundary if boundary else "not reliably identified"))
    relevant = [b for b in branches if b.classification != "IGNORE"]
    ignored = len(branches) - len(relevant)
    actions = []
    for branch in relevant:
        matches = [p for p in pulls if p.get("head", {}).get("ref") == branch.name
                   and (p.get("head", {}).get("repo") or {}).get("full_name", "").lower()
                   == (repository or "").lower()]
        matches.sort(key=lambda p: p.get("state") != "open")
        pr = matches[0] if matches else None
        if pr and branch.classification == "REVIEW" and pr.get("state") == "open":
            branch.classification = "INTEGRATE-CANDIDATE"
        print(f"\n{evidence(branch, default)}")
        if not pr and mode == "finish":
            if api and not dry_run:
                pr = api.create_pr(branch.name, default)
                print(f"Created handover PR #{pr['number']} for {branch.name}")
            else:
                print(f"Would create handover PR for {branch.name} (if no existing PR)")
        number = pr["number"] if pr else None
        comments = api.comments(number) if api and number else []
        if mode == "finish":
            content = f"## FINISH MODE\n\n{evidence(branch, default)}\n\n{QUESTIONS}"
        else:
            content = start_text(branch, default, comments, pr)
        if number and api:
            reconcile_comment(api, dry_run, number, mode, content, comments)
        elif not number:
            print(f"Would create {mode} comment on handover PR for {branch.name}" if mode == "finish"
                  else f"No PR available for {branch.name}; review the branch directly.")
        target = f"PR #{number}" if number else f"branch `{safe(branch.name)}` (PR not identified)"
        actions.append(f"- [ ] {'Explain unresolved work in' if mode == 'finish' else 'Review'} {target}"
                       + (f" — {branch.classification}" if mode == "start" else ""))
    title = "Repository handover TODO" if mode == "finish" else "Repository takeover TODO"
    if mode == "finish":
        body = (f"## Needs attention\n\n- [ ] Confirm that `{safe(default)}` is the intended handover baseline\n"
                + "\n".join(actions) + "\n- [ ] Confirm that CI/tests pass on the intended baseline\n"
                "- [ ] Resolve any remaining handover ambiguity")
    else:
        assessment = ("UNCERTAIN - REVIEW BEFORE STARTING" if relevant or not api else
                      "RELIABLE WITH RESERVATIONS")
        explanation = (f"It is unclear whether `{safe(default)}` represents the intended final state. "
                       "Review the unresolved work before substantial new development." if relevant or not api else
                       f"`{safe(default)}` appears usable with reservations; confirm the intended baseline and CI.")
        body = (f"## Recommended starting point\n\n**{assessment}**\n\n{explanation}\n\n"
                "## Needs attention\n\n" + ("\n".join(actions) or "- [ ] Confirm the baseline and CI with maintainers")
                + f"\n\n## No action currently suggested\n\n{ignored} other branches contain no "
                "apparently consequential unresolved work. Patch equivalence is not proof of intent.")
    body += ("\n\n**FACT:** Default HEAD `" + head + "`.\n\n**HEURISTIC:** Settled boundary: "
             + (f"`{boundary}`" if boundary else "No reliable settled boundary could be identified.")
             + "\n\n**UNKNOWN:** The intended final state requires human confirmation.")
    existing = next((i for i in issues if i.get("title") == title), None)
    original = existing.get("body") or "" if existing else ""
    updated = replace_section(original, mode + "-issue", body)
    action = "update" if existing else "create"
    print(f"\n{'Would ' if dry_run else ''}{action.capitalize()} issue: {title}\n\n{updated}")
    if api and not dry_run:
        if existing:
            if updated != original:
                api.update_issue(existing["number"], updated)
        else:
            api.create_issue(title, updated)
    return body
