#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
from pathlib import Path

from tracker.scanner import scan_repositories

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config" / "track_config.json"
REPORT_DIR = BASE / "reports"
REPORT_DIR.mkdir(exist_ok=True)

now = dt.datetime.now()
stamp = now.strftime("%Y-%m-%d")
output = REPORT_DIR / f"{stamp}-baseline.md"

data = scan_repositories(str(CONFIG))

track_order = ["finance", "engineering", "soc_auto_design", "family"]
track_names = data["trend"]["labels_map"]

lines: list[str] = []
lines.append(f"# Project Track Baseline ({stamp})")
lines.append("")
lines.append(f"- Generated: {data['generated_at']}")
lines.append(f"- Owner: {data['owner']}")
lines.append(f"- Total repos: {data['summary']['total_repos']}")
lines.append(f"- Active repos (30d): {data['summary']['active_repos_30d']}")
lines.append(f"- Commits (30d): {data['summary']['total_commits_30d']}")
lines.append(f"- Issue hits: {data['summary']['total_issue_hits']}")
lines.append("")

for t in track_order:
    s = data["track_summary"][t]
    lines.append(f"## {track_names[t]}")
    lines.append("")
    lines.append(
        f"- repos: {s['repos']} | active: {s['active_repos']} | commits30d: {s['commits_30d']} | issues: {s['issues']} | avg progress: {s['avg_progress']}"
    )
    lines.append("")
    lines.append("| Repo | Progress | Stage | Commits30d | Dirty | Last Commit |")
    lines.append("|---|---:|---|---:|---:|---|")
    for r in data["repos"]:
        if r["track"] != t:
            continue
        dirty = r["status"]["dirty"]["modified"] + r["status"]["dirty"]["untracked"]
        last = r["status"]["last_commit"]["date"] or "-"
        lines.append(
            f"| {r['name']} | {r['progress']['score']} | {r['progress']['stage']} | {r['commits']['last_30d']} | {dirty} | {last} |"
        )
    lines.append("")

output.write_text("\n".join(lines), encoding="utf-8")
print(str(output))
