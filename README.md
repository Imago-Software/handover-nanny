# handover-nanny
A tool to help closing teams handover their code base in a reasonable state, and to help new teams get to grips with the code when it isn't

## Repository handover prototype

Run **Repository handover** from Actions → Run workflow on the default branch.
The repository must allow GitHub Actions to create pull requests in its Actions
settings. The workflow uses `GITHUB_TOKEN` with read access to contents and
write access to issues and pull requests; no personal token is required.

- **finish**: the outgoing team gets a handover TODO issue and a review PR
  comment for each unresolved branch. If no PR exists, one is created. Add a
  separate comment containing `HANDOVER STATUS` and answer the questions in
  the generated comment. Nothing is merged or deleted.
- **start**: the incoming team gets a takeover TODO issue and advisory PR
  comments comparing current evidence with any structured human statements.
  Verify the baseline, CI and unresolved work with maintainers before relying
  on the assessment.

The analysis uses ancestry, patch equivalence, changed paths and PR state, not
developer intent or code quality. A settled boundary is only a conservative
candidate; old unresolved branches are still examined. Patch-equivalent
branches may be ignored, but equivalence does not prove that they were
deliberately abandoned. Classifications and starting-point assessments are
advisory, not guarantees. Closed PRs are reported rather than reopened.
Generated sections are marked and updated on reruns; write human notes outside
the markers or in separate comments. Closed TODO issues are updated but not
reopened automatically.

### Local dry run

Requires Python 3.10+ and Git. From the repository to analyse, fetch all remote
branches and run the tool using its path:

```sh
git fetch --no-tags origin '+refs/heads/*:refs/remotes/origin/*'
python3 /path/to/handover-nanny/src/cli.py --mode finish --dry-run --default-branch main
python3 /path/to/handover-nanny/src/cli.py --mode start --dry-run --default-branch main
```

Set `GITHUB_REPOSITORY` (`owner/repo`) and `GITHUB_TOKEN` to read actual PRs,
issues and comments during a dry run. Without them the tool works offline but
cannot determine whether those artefacts already exist or read human comments.
It prints proposed changes and never writes to GitHub in dry-run mode. The
default branch comes from GitHub when authenticated, or from `origin/HEAD`
(otherwise the current branch); `--default-branch` overrides either.

The workflow examines `origin` remote-tracking branches and the default
branch's complete history. It does not merge, delete, force-push, rewrite
history, or close PRs. GitHub may prevent PR creation because of repository
settings or branch restrictions; fix the permission or review that branch
manually.
