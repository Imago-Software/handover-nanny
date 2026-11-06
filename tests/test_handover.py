import contextlib
import copy
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from git_analysis import analyse
from report import run


class FakeGitHub:
    def __init__(self):
        self.prs = []
        self.issue_list = []
        self.comment_list = {}
        self.writes = []

    def pulls(self, default):
        return copy.deepcopy(self.prs)

    def issues(self):
        return copy.deepcopy(self.issue_list)

    def comments(self, number):
        return copy.deepcopy(self.comment_list.get(number, []))

    def create_pr(self, branch, default):
        self.writes.append("pr")
        pr = {"number": 10 + len(self.prs), "state": "open",
              "head": {"ref": branch, "repo": {"full_name": "org/repo"}}}
        self.prs.append(pr)
        return pr

    def create_issue(self, title, body):
        self.writes.append("issue")
        self.issue_list.append({"number": 100 + len(self.issue_list), "title": title, "body": body})

    def update_issue(self, number, body):
        self.writes.append("update issue")
        next(i for i in self.issue_list if i["number"] == number)["body"] = body

    def create_comment(self, number, body):
        self.writes.append("comment")
        self.comment_list.setdefault(number, []).append({
            "id": 1000 + sum(map(len, self.comment_list.values())), "body": body,
            "user": {"login": "github-actions[bot]", "type": "Bot"}})

    def update_comment(self, comment_id, body):
        self.writes.append("update comment")
        next(c for comments in self.comment_list.values() for c in comments
             if c["id"] == comment_id)["body"] = body


class GitHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.temp.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Tester")
        self.git("config", "user.email", "tester@example.invalid")
        self.commit("base", "base")

    def tearDown(self):
        os.chdir(self.old)
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(["git", *args], stderr=subprocess.PIPE, text=True).strip()

    def commit(self, file, text):
        Path(file).write_text(text)
        self.git("add", file)
        self.git("commit", "-qm", text)

    def refs(self, *branches):
        for branch in branches:
            self.git("update-ref", f"refs/remotes/origin/{branch}", self.git("rev-parse", branch))

    def analyse(self):
        return analyse("main")

    def test_merged_branch_is_ignored_and_merge_is_boundary(self):
        self.git("checkout", "-qb", "feature")
        self.commit("feature", "feature")
        self.git("checkout", "-q", "main")
        self.git("merge", "--no-ff", "-qm", "merge feature", "feature")
        self.refs("main", "feature")
        head, boundary, branches = self.analyse()
        self.assertEqual(boundary, head)
        self.assertTrue(branches[0].merged)
        self.assertEqual(branches[0].classification, "IGNORE")

    def test_cherry_picked_branch_is_ignored(self):
        self.git("checkout", "-qb", "stale")
        self.commit("work", "work")
        change = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "main")
        self.commit("other", "other")
        self.git("cherry-pick", change)
        self.refs("main", "stale")
        _, _, branches = self.analyse()
        self.assertFalse(branches[0].merged)
        self.assertEqual(branches[0].commits, [])
        self.assertEqual(branches[0].classification, "IGNORE")

    def test_unique_work_and_main_merged_into_feature(self):
        self.git("checkout", "-qb", "feature")
        self.commit("first", "first")
        self.git("checkout", "-q", "main")
        self.commit("mainwork", "main work")
        self.git("checkout", "-q", "feature")
        self.git("merge", "--no-ff", "-qm", "merge main", "main")
        self.commit("last", "last")
        self.refs("main", "feature")
        _, boundary, branches = self.analyse()
        branch = branches[0]
        self.assertEqual(branch.classification, "REVIEW")
        self.assertEqual(branch.behind, 0)
        self.assertEqual(len(branch.commits), 2)
        self.assertTrue(any("last" in commit for commit in branch.commits))
        self.assertIn("last", branch.files)
        self.assertIsNone(boundary)

    def test_finish_start_and_rerun_existing_pr(self):
        self.git("checkout", "-qb", "feature")
        self.commit("work", "work")
        self.refs("main", "feature")
        head, boundary, branches = self.analyse()
        api = FakeGitHub()
        api.create_pr("feature", "main")
        api.writes.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            run("finish", "main", head, boundary, branches, api, repository="org/repo")
            run("finish", "main", head, boundary, branches, api, repository="org/repo")
        self.assertEqual(api.writes, ["comment", "issue"])
        self.assertEqual(len(api.prs), 1)
        api.comment_list[10].append({"id": 77, "user": {"type": "User", "login": "human"},
                                     "body": "HANDOVER STATUS\nCurrent state: PARTIAL\nMissing tests: integration"})
        with contextlib.redirect_stdout(io.StringIO()):
            body = run("start", "main", head, boundary, branches, api, repository="org/repo")
            run("start", "main", head, boundary, branches, api, repository="org/repo")
        self.assertIn("UNCERTAIN - REVIEW BEFORE STARTING", body)
        self.assertEqual(len(api.issue_list), 2)
        self.assertEqual(len(api.comment_list[10]), 3)
        start_comment = api.comment_list[10][-1]["body"]
        self.assertIn("HUMAN STATEMENT (unverified)", start_comment)
        self.assertIn("Current state: PARTIAL", start_comment)
        self.assertIn("cannot be verified", start_comment)

    def test_create_and_dry_run_preserve_human_text(self):
        self.git("checkout", "-qb", "new")
        self.commit("work", "work")
        self.refs("main", "new")
        head, boundary, branches = self.analyse()
        api = FakeGitHub()
        api.issue_list.append({"number": 1, "title": "Repository handover TODO", "body": "Human notes"})
        with contextlib.redirect_stdout(io.StringIO()):
            run("finish", "main", head, boundary, branches, api, dry_run=True, repository="org/repo")
        self.assertFalse(api.writes)
        with contextlib.redirect_stdout(io.StringIO()):
            run("finish", "main", head, boundary, branches, api, repository="org/repo")
            run("finish", "main", head, boundary, branches, api, repository="org/repo")
        self.assertEqual(len(api.prs), 1)
        self.assertEqual(len(api.comment_list[10]), 1)
        self.assertEqual(len(api.issue_list), 1)
        self.assertTrue(api.issue_list[0]["body"].startswith("Human notes\n"))


if __name__ == "__main__":
    unittest.main()
