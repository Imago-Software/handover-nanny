"""Command-line entry point for repository handover analysis."""

import argparse
import os
import subprocess
import sys

from git_analysis import analyse, default_branch
from github_api import GitHub
from report import run


def main():
    parser = argparse.ArgumentParser(description="Review unresolved repository handover work.")
    parser.add_argument("--mode", choices=("finish", "start"), required=True)
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing to GitHub")
    parser.add_argument("--default-branch", help="Override default branch (especially for offline use)")
    args = parser.parse_args()
    repository = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    if not args.dry_run and not (repository and token):
        parser.error("GITHUB_REPOSITORY and GITHUB_TOKEN are required unless --dry-run is used")
    api = GitHub(repository, token, os.environ.get("GITHUB_API_URL", "https://api.github.com")) if repository and token else None
    try:
        default = args.default_branch or (api.repository()["default_branch"] if api else default_branch())
        head, boundary, branches = analyse(default)
        summary = run(args.mode, default, head, boundary, branches, api, args.dry_run, repository)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as file:
                file.write(summary + "\n")
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f"Analysis failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
