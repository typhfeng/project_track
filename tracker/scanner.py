from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RE_OWNER = re.compile(r"github\.com[:/]([^/]+)/([^/.]+)(?:\.git)?$")
RE_STATUS_AHEAD = re.compile(r"ahead (\d+)")
RE_STATUS_BEHIND = re.compile(r"behind (\d+)")
ISSUE_REGEX = r"(TODO|FIXME|BUG|HACK|XXX|BLOCKER|RISK)"
COMMIT_ALERT_REGEX = re.compile(r"\b(fix|bug|error|fail|todo|problem|blocker|risk|regress)\b", re.IGNORECASE)


@dataclass
class RepoConfig:
    owner: str
    scan_roots: list[str]
    include_repos: list[str]
    max_repo_depth: int
    cache_ttl_seconds: int
    exclude_paths: list[str]
    track_overrides: dict[str, str]


def load_config(config_path: str) -> RepoConfig:
    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return RepoConfig(
        owner=raw.get("owner", "typhfeng"),
        scan_roots=raw.get("scan_roots", []),
        include_repos=raw.get("include_repos", []),
        max_repo_depth=int(raw.get("max_repo_depth", 6)),
        cache_ttl_seconds=int(raw.get("cache_ttl_seconds", 120)),
        exclude_paths=raw.get("exclude_paths", []),
        track_overrides=raw.get("track_overrides", {}),
    )


def run_cmd(args: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=False)
        return proc.returncode, proc.stdout.strip()
    except FileNotFoundError:
        # Keep scanner resilient when optional tools are missing in PATH.
        return 127, ""


def discover_git_repos(cfg: RepoConfig) -> list[str]:
    repos: set[str] = set()
    for repo in cfg.include_repos:
        if Path(repo, ".git").is_dir():
            repos.add(repo)

    for root in cfg.scan_roots:
        _, out = run_cmd([
            "find",
            root,
            "-maxdepth",
            str(cfg.max_repo_depth),
            "-type",
            "d",
            "-name",
            ".git",
        ])
        if not out:
            continue
        for line in out.splitlines():
            repo = str(Path(line).parent)
            repos.add(repo)

    filtered = []
    for repo in sorted(repos):
        if any(repo.startswith(ex) for ex in cfg.exclude_paths):
            continue
        filtered.append(repo)
    return filtered


def parse_remote_owner_repo(remote_url: str) -> tuple[str, str] | None:
    m = RE_OWNER.search(remote_url)
    if not m:
        return None
    return m.group(1), m.group(2)


def classify_track(path: str, repo_name: str, cfg: RepoConfig) -> str:
    for prefix, track in cfg.track_overrides.items():
        if path == prefix or path.startswith(prefix + "/"):
            return track

    key = f"{path} {repo_name}".lower()

    finance_kw = ["finance", "stk", "trader", "poly", "trading", "quant", "moomoo", "webull"]
    engineering_kw = ["daytalk", "npu", "noc", "mec", "rtl", "arm", "chip", "soc"]
    soc_auto_kw = ["auto-design", "autodesign", "openlane", "eda", "chipgen", "autoflow"]
    family_kw = ["family", "home", "ella", "anna"]

    if any(k in key for k in finance_kw):
        return "finance"
    if any(k in key for k in engineering_kw):
        return "engineering"
    if any(k in key for k in soc_auto_kw):
        return "soc_auto_design"
    if any(k in key for k in family_kw):
        return "family"
    return "engineering"


def get_repo_status(repo: str) -> dict[str, Any]:
    _, branch = run_cmd(["git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"])
    _, status_sb = run_cmd(["git", "-C", repo, "status", "-sb"])
    status_line = status_sb.splitlines()[0] if status_sb else ""

    _, last = run_cmd([
        "git",
        "-C",
        repo,
        "log",
        "-1",
        "--date=iso",
        "--pretty=format:%ad|%h|%s",
    ])
    last_date = ""
    last_hash = ""
    last_subject = ""
    if last:
        parts = last.split("|", 2)
        if len(parts) == 3:
            last_date, last_hash, last_subject = parts

    _, porcelain = run_cmd(["git", "-C", repo, "status", "--porcelain"])
    modified = 0
    untracked = 0
    if porcelain:
        for line in porcelain.splitlines():
            if line.startswith("??"):
                untracked += 1
            elif line.strip():
                modified += 1

    ahead = 0
    behind = 0
    ma = RE_STATUS_AHEAD.search(status_line)
    mb = RE_STATUS_BEHIND.search(status_line)
    if ma:
        ahead = int(ma.group(1))
    if mb:
        behind = int(mb.group(1))

    return {
        "branch": branch or "-",
        "status_line": status_line.replace("## ", "").strip(),
        "last_commit": {
            "date": last_date,
            "hash": last_hash,
            "subject": last_subject,
        },
        "dirty": {
            "modified": modified,
            "untracked": untracked,
        },
        "ahead": ahead,
        "behind": behind,
    }


def count_commits_since(repo: str, days: int) -> int:
    _, out = run_cmd([
        "git",
        "-C",
        repo,
        "rev-list",
        "--count",
        "HEAD",
        f"--since={days}.days",
    ])
    try:
        return int(out.strip()) if out else 0
    except ValueError:
        return 0


def weekly_commit_counts(repo: str, weeks: int = 12) -> dict[str, int]:
    now = dt.datetime.now()
    since_days = weeks * 7
    _, out = run_cmd([
        "git",
        "-C",
        repo,
        "log",
        f"--since={since_days}.days",
        "--date=format:%G-W%V",
        "--pretty=format:%ad",
    ])
    counts: dict[str, int] = {}
    if not out:
        return counts

    for week in out.splitlines():
        week = week.strip()
        if not week:
            continue
        counts[week] = counts.get(week, 0) + 1

    # keep only recent N weeks in timeline space
    labels = []
    current = now
    for _ in range(weeks):
        labels.append(current.strftime("%G-W%V"))
        current -= dt.timedelta(days=7)

    label_set = set(labels)
    return {k: v for k, v in counts.items() if k in label_set}


def collect_issue_matches(repo: str, max_count: int = 120) -> list[dict[str, Any]]:
    if shutil.which("rg"):
        cmd = [
            "rg",
            "-n",
            "-S",
            "-i",
            "--hidden",
            "--glob",
            "!.git",
            "--glob",
            "!venv/**",
            "--glob",
            "!.venv/**",
            "--glob",
            "!node_modules/**",
            "--glob",
            "!build/**",
            "--glob",
            "!output/**",
            "--glob",
            "!dist/**",
            "--max-filesize",
            "1M",
            "--max-count",
            str(max_count),
            ISSUE_REGEX,
            repo,
        ]
    else:
        # Fallback for environments where ripgrep is not available.
        cmd = [
            "grep",
            "-RInE",
            ISSUE_REGEX,
            repo,
            "--exclude-dir=.git",
            "--exclude-dir=venv",
            "--exclude-dir=.venv",
            "--exclude-dir=node_modules",
            "--exclude-dir=build",
            "--exclude-dir=output",
            "--exclude-dir=dist",
        ]
    code, out = run_cmd(cmd)
    if code not in (0, 1) or not out:
        return []

    entries: list[dict[str, Any]] = []
    for line in out.splitlines():
        # format: /path/file:line:text
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        p, line_no, text = parts
        rel = os.path.relpath(p, repo)
        entries.append({
            "file": rel,
            "line": int(line_no) if line_no.isdigit() else 0,
            "text": text.strip(),
        })
        if len(entries) >= max_count:
            break
    return entries


def collect_commit_alerts(repo: str, days: int = 180, max_count: int = 80) -> list[dict[str, str]]:
    _, out = run_cmd([
        "git",
        "-C",
        repo,
        "log",
        f"--since={days}.days",
        "--date=short",
        "--pretty=format:%ad|%h|%s",
    ])
    alerts: list[dict[str, str]] = []
    if not out:
        return alerts

    for line in out.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        date, h, subj = parts
        if COMMIT_ALERT_REGEX.search(subj):
            alerts.append({"date": date, "hash": h, "subject": subj})
        if len(alerts) >= max_count:
            break
    return alerts


def parse_iso_date(date_str: str) -> dt.datetime | None:
    if not date_str:
        return None
    try:
        # date format from git --date=iso
        return dt.datetime.fromisoformat(date_str)
    except ValueError:
        return None


def calc_progress(repo_metrics: dict[str, Any]) -> tuple[int, str]:
    now = dt.datetime.now(dt.timezone.utc)
    last_date = parse_iso_date(repo_metrics["status"]["last_commit"]["date"])
    if last_date is None:
        return 0, "Not Started"

    # Normalize timezone for delta
    if last_date.tzinfo is None:
        last_date = last_date.replace(tzinfo=dt.timezone.utc)

    days_since = max((now - last_date).days, 0)
    commits_30 = repo_metrics["commits"]["last_30d"]
    dirty = repo_metrics["status"]["dirty"]["modified"] + repo_metrics["status"]["dirty"]["untracked"]
    issues = repo_metrics["issues"]["total"]

    recency_score = max(0, 30 - min(days_since, 30))
    activity_score = min(commits_30 * 3, 35)
    hygiene_penalty = min(dirty * 2, 20)
    issue_penalty = min(issues // 30, 10)

    score = 20 + recency_score + activity_score - hygiene_penalty - issue_penalty
    score = max(0, min(100, score))

    if commits_30 == 0 and days_since > 90:
        stage = "Stalled"
    elif commits_30 >= 12 and days_since <= 7:
        stage = "Accelerating"
    elif commits_30 >= 4 and days_since <= 30:
        stage = "In Progress"
    elif days_since <= 60:
        stage = "Maintaining"
    else:
        stage = "At Risk"

    return score, stage


def build_week_labels(weeks: int = 12) -> list[str]:
    labels: list[str] = []
    current = dt.datetime.now()
    for _ in range(weeks):
        labels.append(current.strftime("%G-W%V"))
        current -= dt.timedelta(days=7)
    labels.reverse()
    return labels


def repo_id(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]


def scan_repositories(config_path: str) -> dict[str, Any]:
    cfg = load_config(config_path)
    repos = discover_git_repos(cfg)

    tracked: list[dict[str, Any]] = []
    issue_search_pool: list[dict[str, Any]] = []

    for repo in repos:
        code, remote = run_cmd(["git", "-C", repo, "remote", "get-url", "origin"])
        if code != 0 or not remote:
            continue
        parsed = parse_remote_owner_repo(remote)
        if not parsed:
            continue
        owner, name = parsed
        if owner.lower() != cfg.owner.lower():
            continue

        track = classify_track(repo, name, cfg)
        status = get_repo_status(repo)
        commits = {
            "last_7d": count_commits_since(repo, 7),
            "last_30d": count_commits_since(repo, 30),
            "last_90d": count_commits_since(repo, 90),
        }
        weekly_counts = weekly_commit_counts(repo, weeks=12)
        issue_hits = collect_issue_matches(repo, max_count=120)
        commit_alerts = collect_commit_alerts(repo, days=180, max_count=80)

        metrics = {
            "id": repo_id(repo),
            "name": name,
            "path": repo,
            "remote": remote,
            "track": track,
            "status": status,
            "commits": commits,
            "weekly_commits": weekly_counts,
            "issues": {
                "total": len(issue_hits),
                "hits": issue_hits[:80],
            },
            "commit_alerts": commit_alerts[:40],
        }
        progress, stage = calc_progress(metrics)
        metrics["progress"] = {
            "score": progress,
            "stage": stage,
        }

        tracked.append(metrics)

        for hit in issue_hits[:80]:
            issue_search_pool.append(
                {
                    "repo": name,
                    "path": repo,
                    "track": track,
                    "type": "code_issue",
                    "title": f"{hit['file']}:{hit['line']}",
                    "content": hit["text"],
                }
            )
        for alert in commit_alerts[:40]:
            issue_search_pool.append(
                {
                    "repo": name,
                    "path": repo,
                    "track": track,
                    "type": "commit_alert",
                    "title": f"{alert['date']} {alert['hash']}",
                    "content": alert["subject"],
                }
            )

    tracks = ["finance", "engineering", "soc_auto_design", "family"]
    track_labels = {
        "finance": "Finance",
        "engineering": "Engineering",
        "soc_auto_design": "SoC Auto Design",
        "family": "Family",
    }

    week_labels = build_week_labels(weeks=12)
    trend = {t: {w: 0 for w in week_labels} for t in tracks}

    track_summary: dict[str, dict[str, Any]] = {
        t: {
            "label": track_labels[t],
            "repos": 0,
            "active_repos": 0,
            "commits_30d": 0,
            "commits_90d": 0,
            "issues": 0,
            "avg_progress": 0,
        }
        for t in tracks
    }

    for repo in tracked:
        t = repo["track"] if repo["track"] in track_summary else "engineering"
        s = track_summary[t]
        s["repos"] += 1
        s["commits_30d"] += repo["commits"]["last_30d"]
        s["commits_90d"] += repo["commits"]["last_90d"]
        s["issues"] += repo["issues"]["total"]
        s["avg_progress"] += repo["progress"]["score"]
        if repo["commits"]["last_30d"] > 0:
            s["active_repos"] += 1

        for w, c in repo["weekly_commits"].items():
            if w in trend[t]:
                trend[t][w] += c

    for t in tracks:
        repos_count = track_summary[t]["repos"]
        track_summary[t]["avg_progress"] = (
            round(track_summary[t]["avg_progress"] / repos_count, 1) if repos_count else 0.0
        )

    tracked.sort(key=lambda r: (r["progress"]["score"], r["commits"]["last_30d"]), reverse=True)

    dashboard = {
        "generated_at": dt.datetime.now().isoformat(),
        "owner": cfg.owner,
        "scan_scope": cfg.scan_roots,
        "summary": {
            "total_repos": len(tracked),
            "active_repos_30d": sum(1 for r in tracked if r["commits"]["last_30d"] > 0),
            "total_commits_30d": sum(r["commits"]["last_30d"] for r in tracked),
            "total_commits_90d": sum(r["commits"]["last_90d"] for r in tracked),
            "dirty_repos": sum(
                1
                for r in tracked
                if (r["status"]["dirty"]["modified"] + r["status"]["dirty"]["untracked"]) > 0
            ),
            "total_issue_hits": sum(r["issues"]["total"] for r in tracked),
        },
        "track_summary": track_summary,
        "trend": {
            "labels": week_labels,
            "series": {t: [trend[t][w] for w in week_labels] for t in tracks},
            "labels_map": track_labels,
        },
        "repos": tracked,
        "search_pool": issue_search_pool,
    }
    return dashboard


def search_key_issues(dashboard: dict[str, Any], query: str, limit: int = 80) -> list[dict[str, Any]]:
    q = query.strip().lower()
    if not q:
        return dashboard.get("search_pool", [])[:limit]

    results = []
    for item in dashboard.get("search_pool", []):
        hay = f"{item.get('repo', '')} {item.get('title', '')} {item.get('content', '')} {item.get('track', '')}".lower()
        if q in hay:
            results.append(item)
        if len(results) >= limit:
            break
    return results
