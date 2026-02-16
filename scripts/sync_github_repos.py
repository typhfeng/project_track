#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.github.com"


def http_get_json(url: str, token: str | None) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "project-track-sync/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_git(args: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired as e:
        msg = f"command timeout after {timeout}s: {' '.join(args)}"
        extra = (e.stdout or "") + (e.stderr or "")
        return 124, (msg + "\n" + extra).strip()


def fetch_repos(owner: str, token: str | None) -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    page = 1

    use_user_api = False
    if token:
        try:
            me = http_get_json(f"{API}/user", token)
            if str(me.get("login", "")).lower() == owner.lower():
                use_user_api = True
        except Exception:
            use_user_api = False

    while True:
        if use_user_api:
            q = urlencode({"per_page": 100, "page": page, "type": "owner", "sort": "full_name"})
            url = f"{API}/user/repos?{q}"
        else:
            q = urlencode({"per_page": 100, "page": page, "sort": "full_name"})
            url = f"{API}/users/{owner}/repos?{q}"

        data = http_get_json(url, token)
        if not isinstance(data, list) or not data:
            break
        repos.extend(data)
        page += 1

    # Stable order
    repos.sort(key=lambda r: r.get("name", "").lower())
    return repos


def sync_repo(repo: dict[str, Any], root: Path, do_pull: bool, protocol: str) -> tuple[str, str]:
    name = repo["name"]
    dest = root / name
    ssh_url = repo.get("ssh_url", "")
    clone_url = repo.get("clone_url", "")

    if (dest / ".git").is_dir():
        if do_pull:
            code, out = run_git(["git", "-C", str(dest), "pull", "--ff-only"])
            return ("updated" if code == 0 else "pull_failed", out)
        return ("exists", "")

    dest.parent.mkdir(parents=True, exist_ok=True)
    urls: list[str] = []
    if protocol == "https":
        urls = [clone_url, ssh_url]
    elif protocol == "ssh":
        urls = [ssh_url, clone_url]
    else:
        urls = [ssh_url, clone_url]

    for url in urls:
        if not url:
            continue
        code, out = run_git(["git", "clone", url, str(dest)], timeout=90)
        if code == 0:
            return ("cloned", out)
        # cleanup broken partial clone before next retry
        if dest.exists() and not (dest / ".git").is_dir():
            try:
                shutil.rmtree(dest, ignore_errors=True)
            except Exception:
                pass
    return ("clone_failed", out if 'out' in locals() else "clone failed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Clone/sync all GitHub repos for an owner into ~/git/<owner>")
    parser.add_argument("--owner", default="typhfeng", help="GitHub owner/login")
    parser.add_argument("--dest", default="~/git", help="Base destination directory")
    parser.add_argument("--pull", action="store_true", help="Pull existing repos")
    parser.add_argument(
        "--protocol",
        choices=["auto", "ssh", "https"],
        default="auto",
        help="Clone protocol preference",
    )
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    base = Path(os.path.expanduser(args.dest)).resolve()
    owner_root = base / args.owner
    owner_root.mkdir(parents=True, exist_ok=True)

    print(f"[info] owner={args.owner}")
    print(f"[info] dest={owner_root}")
    print(f"[info] auth={'token' if token else 'none (public repos only)'}")
    print(f"[info] protocol={args.protocol}")

    try:
        repos = fetch_repos(args.owner, token)
    except Exception as e:
        print(f"[error] failed to fetch repository list: {e}", file=sys.stderr)
        return 2

    if not repos:
        print("[warn] no repositories found")
        return 0

    stats = {"cloned": 0, "updated": 0, "exists": 0, "clone_failed": 0, "pull_failed": 0}

    for r in repos:
        name = r.get("name", "")
        if not name:
            continue
        status, msg = sync_repo(r, owner_root, args.pull, args.protocol)
        if status in stats:
            stats[status] += 1
        else:
            stats["clone_failed"] += 1
        print(f"[{status}] {name}")
        if status in ("clone_failed", "pull_failed") and msg:
            print(msg)

    print("[summary]", json.dumps(stats, ensure_ascii=False))
    print(f"[summary] total={len(repos)} repos, root={owner_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
