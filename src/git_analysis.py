"""Small, conservative Git topology analysis."""

import subprocess
from dataclasses import dataclass


def git(*args):
    return subprocess.check_output(
        ["git", *args], text=True, stderr=subprocess.PIPE
    ).strip()


@dataclass
class Branch:
    name: str
    ref: str
    merged: bool
    base: str | None
    ahead: int
    behind: int
    commits: list[str]
    files: list[str]
    unique_merges: int
    classification: str
    recent: str


def default_branch(explicit=None):
    if explicit:
        return explicit
    try:
        return git("symbolic-ref", "--short", "refs/remotes/origin/HEAD").removeprefix("origin/")
    except subprocess.CalledProcessError:
        return git("branch", "--show-current")


def analyse(default):
    remote_default = f"refs/remotes/origin/{default}"
    try:
        git("rev-parse", "--verify", remote_default)
        baseline = remote_default
    except subprocess.CalledProcessError:
        baseline = f"refs/heads/{default}"
        git("rev-parse", "--verify", baseline)
    head = git("rev-parse", baseline)
    refs = git("for-each-ref", "--format=%(refname)", "refs/remotes/origin")
    branches = []
    for ref in refs.splitlines():
        name = ref.removeprefix("refs/remotes/origin/")
        if name in ("HEAD", default):
            continue
        try:
            base = git("merge-base", baseline, ref)
        except subprocess.CalledProcessError:
            base = None
        recent = git("log", "-1", "--format=%h %as %an: %s", ref)
        if not base:
            branches.append(Branch(name, ref, False, None, 0, 0, [], [], 0, "UNCERTAIN", recent))
            continue
        counts = git("rev-list", "--left-right", "--count", f"{baseline}...{ref}").split()
        behind, ahead = map(int, counts)
        merged = ahead == 0
        commits = git("log", "--format=%h %as %an: %s", "--right-only", "--cherry-pick",
                      "--no-merges", f"{baseline}...{ref}").splitlines()
        files = git("diff", "--name-only", f"{base}..{ref}").splitlines()
        unique_merges = int(git("rev-list", "--count", "--merges", f"{baseline}..{ref}"))
        if merged or (not commits and not unique_merges):
            classification = "IGNORE"
        elif unique_merges and not commits:
            classification = "UNCERTAIN"
        else:
            classification = "REVIEW"
        branches.append(Branch(name, ref, merged, base, ahead, behind, commits, files,
                               unique_merges, classification, recent))
    # A merge is a plausible boundary only when no unresolved branch diverged earlier.
    boundary = None
    for candidate in git("rev-list", "--first-parent", "--merges", baseline).splitlines():
        if all(b.classification == "IGNORE" or (
            b.base and subprocess.run(
                ["git", "merge-base", "--is-ancestor", candidate, b.base],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            ).returncode == 0
        ) for b in branches):
            boundary = candidate
            break
    return head, boundary, branches
