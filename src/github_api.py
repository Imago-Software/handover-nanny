"""Minimal GitHub REST API client."""

import json
import urllib.error
import urllib.parse
import urllib.request


class GitHub:
    def __init__(self, repository, token, api_url="https://api.github.com"):
        self.root = api_url.rstrip("/") + "/repos/" + repository
        self.token = token

    def request(self, method, path, data=None):
        body = json.dumps(data).encode() if data is not None else None
        request = urllib.request.Request(
            self.root + path, data=body, method=method,
            headers={"Authorization": "Bearer " + self.token,
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"GitHub API {method} {path}: HTTP {error.code}") from error

    def list(self, path):
        result = []
        separator = "&" if "?" in path else "?"
        page = 1
        while True:
            items = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            result.extend(items)
            if len(items) < 100:
                return result
            page += 1

    def repository(self):
        return self.request("GET", "")

    def pulls(self, default):
        return self.list("/pulls?state=all&base=" + urllib.parse.quote(default, safe=""))

    def issues(self):
        return [i for i in self.list("/issues?state=all") if "pull_request" not in i]

    def comments(self, number):
        return self.list(f"/issues/{number}/comments")

    def create_pr(self, branch, default):
        return self.request("POST", "/pulls", {
            "title": f"Handover: review {branch}", "head": branch, "base": default,
            "body": "Automatically created handover PR for human review. Do not merge without review.",
        })

    def create_issue(self, title, body):
        return self.request("POST", "/issues", {"title": title, "body": body})

    def update_issue(self, number, body):
        return self.request("PATCH", f"/issues/{number}", {"body": body})

    def create_comment(self, number, body):
        return self.request("POST", f"/issues/{number}/comments", {"body": body})

    def update_comment(self, comment_id, body):
        return self.request("PATCH", f"/issues/comments/{comment_id}", {"body": body})
