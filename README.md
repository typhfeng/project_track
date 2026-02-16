# project_track

A standalone Web GUI to monitor and analyze personal project progress across all local repositories owned by `typhfeng`.

## What it does

- Auto-discovers local Git repos and keeps only `origin` repos under `github.com:typhfeng/*`.
- Supports manual repo intervention from Web GUI:
  - add local repo path
  - assign/override track
  - remove repo from monitored list
- Supports track-first review workflow:
  - click track summary card to open group-level repo board
  - click repo to open detailed review panel
- Repo-level review and actions:
  - recent commits + changed files
  - open GitHub issues + local TODO list
  - create GitHub issue
  - add/edit/complete TODO entries
  - sync/pull repo, commit and push changes
- Classifies repos into 4 tracks:
  - Finance
  - Engineering
  - SoC Auto Design
  - Family
- Generates progress analytics:
  - commit throughput (7d/30d/90d)
  - weekly trend (12 weeks)
  - time allocation by track
  - repo progress score + stage
  - dirty workspace status
- Tracks key issues:
  - TODO/FIXME/BUG/HACK/BLOCKER/RISK hits from code
  - commit-message alerts containing risk/fix/problem keywords
  - searchable issue panel in Web GUI

## Directory

- `app.py`: Flask Web service
- `tracker/scanner.py`: repo discovery + metrics engine
- `config/track_config.json`: core scanner settings (`owner`, `scan_roots`, manifest path)
- `config/repo_manifest.json`: manual repo address list (`path`, `track`, `enabled`)
- `templates/index.html`: dashboard page
- `static/styles.css`: UI style
- `static/app.js`: dashboard logic and chart rendering
- `scripts/sync_github_repos.py`: clone/sync all repos from GitHub owner
- `scripts/rebuild_repo_manifest.py`: rebuild manifest from a root directory

## Run

```bash
cd /Users/sunkewei/git/typhfeng/project_track
./run.sh
```

Open:
- http://127.0.0.1:5055

## Generate baseline report

```bash
cd /Users/sunkewei/git/typhfeng/project_track
source .venv/bin/activate
./scripts_build_report.py
```

Output:
- `reports/<YYYY-MM-DD>-baseline.md`

## Clone all GitHub repos to ~/git

```bash
cd /Users/sunkewei/git/typhfeng/project_track
./scripts/sync_github_repos.py --owner typhfeng --dest ~/git --pull
```

Notes:
- If `GITHUB_TOKEN` (or `GH_TOKEN`) is set for the same owner, private repos are included.
- Without token, only public repos are fetched from GitHub API.
- `Create Issue` in Web GUI also requires `GITHUB_TOKEN`/`GH_TOKEN`.

## JSON-driven repo list

Edit this file directly to control monitored repos:
- `/Users/sunkewei/git/typhfeng/project_track/config/repo_manifest.json`

Schema:
```json
{
  "search_root": "/Users/sunkewei/git/typhfeng",
  "repos": [
    { "path": "/Users/sunkewei/git/typhfeng/poly", "track": "finance", "enabled": true }
  ]
}
```

Track values:
- `finance`
- `engineering`
- `soc_auto_design`
- `family`

Regenerate manifest from root:
```bash
cd /Users/sunkewei/git/typhfeng/project_track
./scripts/rebuild_repo_manifest.py --root ~/git/typhfeng --manifest ./config/repo_manifest.json --exclude project_track
```

## Notes

- This repo is independent from `/Users/sunkewei/work/daytalk2026`.
- Default scan scope is `~/git/typhfeng`; edit `config/track_config.json` if needed.
- `config/repo_manifest.json` is the authoritative list for manual repo specification.
- Cache TTL defaults to 120 seconds to balance freshness and scan cost.
