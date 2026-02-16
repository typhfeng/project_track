#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


def run(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(args, capture_output=True, text=True, check=False)
    return p.returncode, p.stdout.strip()


def find_repos(root: Path, max_depth: int) -> list[Path]:
    code, out = run([
        "find",
        str(root),
        "-maxdepth",
        str(max_depth),
        "-type",
        "d",
        "-name",
        ".git",
    ])
    if code != 0 or not out:
        return []
    repos = [Path(line).parent.resolve() for line in out.splitlines() if line.strip()]
    repos.sort()
    return repos


def guess_track(name: str) -> str:
    n = name.lower()
    finance_kw = ["stk", "poly", "trade", "quant", "finance", "stock", "trader"]
    soc_kw = ["soc", "autodesign", "auto-design", "openlane", "eda"]
    family_kw = ["family", "anna", "ella", "home"]
    if any(k in n for k in family_kw):
        return "family"
    if any(k in n for k in soc_kw):
        return "soc_auto_design"
    if any(k in n for k in finance_kw):
        return "finance"
    return "engineering"


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild config/repo_manifest.json from a root folder")
    parser.add_argument("--root", default="~/git/typhfeng", help="Repo search root")
    parser.add_argument("--manifest", default="/Users/sunkewei/git/typhfeng/project_track/config/repo_manifest.json")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--exclude", action="append", default=["project_track"], help="Repo names to exclude")
    args = parser.parse_args()

    root = Path(os.path.expanduser(args.root)).resolve()
    manifest_path = Path(os.path.expanduser(args.manifest)).resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    existing_tracks: dict[str, str] = {}
    if manifest_path.is_file():
        with open(manifest_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for item in raw.get("repos", []):
            if not isinstance(item, dict):
                continue
            p = str(item.get("path", "")).strip()
            t = str(item.get("track", "")).strip()
            if p and t:
                existing_tracks[str(Path(os.path.expanduser(p)).resolve())] = t

    repos = find_repos(root, args.max_depth)
    exclude_names = {x.strip() for x in args.exclude if x.strip()}

    entries = []
    for repo in repos:
        if repo.name in exclude_names:
            continue
        repo_str = str(repo)
        track = existing_tracks.get(repo_str, guess_track(repo.name))
        entries.append({
            "path": repo_str,
            "track": track,
            "enabled": True,
        })

    output = {
        "search_root": str(root),
        "repos": entries,
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"manifest: {manifest_path}")
    print(f"repos: {len(entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
