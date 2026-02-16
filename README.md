# project_track

A standalone Web GUI to monitor and analyze personal project progress across all local repositories owned by `typhfeng`.

## What it does

- Auto-discovers local Git repos and keeps only `origin` repos under `github.com:typhfeng/*`.
- Supports manual repo intervention from Web GUI:
  - add local repo path
  - assign/override track
  - remove repo from monitored list
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
- `config/track_config.json`: scan roots, owner, track overrides
- `templates/index.html`: dashboard page
- `static/styles.css`: UI style
- `static/app.js`: dashboard logic and chart rendering
- `scripts/sync_github_repos.py`: clone/sync all repos from GitHub owner

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

## Notes

- This repo is independent from `/Users/sunkewei/work/daytalk2026`.
- Default scan scope is `/Users/sunkewei/git/typhfeng`; edit `config/track_config.json` if needed.
- `include_repos` in `config/track_config.json` is the authoritative monitored list.
- Cache TTL defaults to 120 seconds to balance freshness and scan cost.
