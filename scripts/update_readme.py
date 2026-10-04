"""Refresh the dynamic sections of the profile README.

Sections are the text between marker comments in README.md:
    <!--COMMITS:START--> ... <!--COMMITS:END-->
    <!--LEETCODE:START--> ... <!--LEETCODE:END-->

Each section updates independently. If one data source fails, its section
is left untouched so the README never ends up blank or broken.

Uses only the Python standard library.
"""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

GH_USER = os.environ.get("GH_USER", "kushaalshyam")
LEETCODE_USER = os.environ.get("LEETCODE_USERNAME", "kushaalshyam")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
README = "README.md"
MAX_COMMITS = 5


# ---------- helpers ----------

def http_json(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def gh_get(path):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-readme-updater",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return http_json(f"https://api.github.com{path}", headers=headers)


def replace_section(text, name, new_body):
    pattern = re.compile(
        rf"(<!--{name}:START-->)(.*?)(<!--{name}:END-->)", re.DOTALL
    )
    if not pattern.search(text):
        raise ValueError(f"markers for {name} not found in README")
    return pattern.sub(lambda m: f"{m.group(1)}\n{new_body}\n{m.group(3)}", text)


def time_ago(iso):
    then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    secs = int((datetime.now(timezone.utc) - then).total_seconds())
    if secs < 3600:
        return f"{max(secs // 60, 1)}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def clean(msg, limit=70):
    line = msg.strip().splitlines()[0] if msg.strip() else "(no message)"
    line = line.replace("|", "/").replace("`", "'")
    return line if len(line) <= limit else line[: limit - 1] + "…"


# ---------- section builders ----------

def build_commits():
    own_profile_repo = f"{GH_USER}/{GH_USER}".lower()
    repos = gh_get(f"/users/{GH_USER}/repos?sort=pushed&per_page=8&type=owner")

    commits = []
    for repo in repos:
        full = repo["full_name"]
        # skip forks and the profile repo itself (the bot's own commits live there)
        if repo.get("fork") or full.lower() == own_profile_repo:
            continue
        try:
            items = gh_get(f"/repos/{full}/commits?author={GH_USER}&per_page=3")
        except Exception:
            continue  # empty repo, or no access
        for c in items:
            commits.append(
                {
                    "repo": repo["name"],
                    "repo_url": repo["html_url"],
                    "msg": clean(c["commit"]["message"]),
                    "url": c["html_url"],
                    "date": c["commit"]["author"]["date"],
                }
            )

    if not commits:
        raise RuntimeError("no public commits found")

    commits.sort(key=lambda c: c["date"], reverse=True)
    lines = [
        f"- [`{c['repo']}`]({c['repo_url']}) · [{c['msg']}]({c['url']}) · _{time_ago(c['date'])}_"
        for c in commits[:MAX_COMMITS]
    ]
    return "\n".join(lines)


LEETCODE_QUERY = """
query userProblemsSolved($username: String!) {
  matchedUser(username: $username) {
    submitStatsGlobal { acSubmissionNum { difficulty count } }
  }
}
"""


def build_leetcode():
    payload = json.dumps(
        {"query": LEETCODE_QUERY, "variables": {"username": LEETCODE_USER}}
    ).encode()
    data = http_json(
        "https://leetcode.com/graphql",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Referer": "https://leetcode.com",
            "User-Agent": "Mozilla/5.0 (profile-readme-updater)",
        },
    )
    user = (data.get("data") or {}).get("matchedUser")
    if not user:
        raise RuntimeError("LeetCode user not found, check LEETCODE_USERNAME")

    counts = {
        row["difficulty"]: row["count"]
        for row in user["submitStatsGlobal"]["acSubmissionNum"]
    }
    return (
        f"**{counts['All']} problems solved on LeetCode** · "
        f"🟢 Easy {counts['Easy']} · 🟡 Medium {counts['Medium']} · 🔴 Hard {counts['Hard']}"
    )


# ---------- main ----------

def main():
    text = open(README, encoding="utf-8").read()
    original = text

    for name, builder in (("COMMITS", build_commits), ("LEETCODE", build_leetcode)):
        try:
            text = replace_section(text, name, builder())
            print(f"[ok] {name} updated")
        except Exception as exc:  # keep going; leave the old section in place
            print(f"[skip] {name}: {exc}", file=sys.stderr)

    if text != original:
        open(README, "w", encoding="utf-8").write(text)
        print("README.md changed")
    else:
        print("No changes")


if __name__ == "__main__":
    main()