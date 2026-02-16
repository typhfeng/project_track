from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from flask import Flask, jsonify, render_template, request

from tracker.scanner import load_config, parse_remote_owner_repo, scan_repositories, search_key_issues

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = os.environ.get(
    "PROJECT_TRACK_CONFIG",
    str(BASE_DIR / "config" / "track_config.json"),
)

app = Flask(__name__)

_cache_lock = threading.Lock()
_cache_data: dict[str, Any] | None = None
_cache_ts: float = 0.0

TRACK_OPTIONS = {"finance", "engineering", "soc_auto_design", "family"}
TODO_RE = re.compile(r"^- \[( |x|X)\] (.*)$")


def _invalidate_cache() -> None:
    global _cache_data, _cache_ts
    with _cache_lock:
        _cache_data = None
        _cache_ts = 0.0


def _read_config_raw() -> dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_config_raw(cfg: dict[str, Any]) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _manifest_path(cfg: dict[str, Any]) -> Path:
    raw = str(cfg.get("repo_manifest_path", "config/repo_manifest.json")).strip()
    p = Path(raw)
    if p.is_absolute():
        return p
    return (Path(CONFIG_PATH).resolve().parent / p).resolve()


def _read_manifest(cfg: dict[str, Any]) -> dict[str, Any]:
    path = _manifest_path(cfg)
    if not path.is_file():
        return {
            "search_root": "~/git/typhfeng",
            "repos": [],
        }
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw.get("repos"), list):
        raw["repos"] = []
    if "search_root" not in raw:
        raw["search_root"] = "~/git/typhfeng"
    return raw


def _write_manifest(cfg: dict[str, Any], manifest: dict[str, Any]) -> None:
    path = _manifest_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _get_cache_ttl() -> int:
    cfg = load_config(CONFIG_PATH)
    return cfg.cache_ttl_seconds


def load_dashboard(force: bool = False) -> dict[str, Any]:
    global _cache_data, _cache_ts
    now = time.time()
    ttl = _get_cache_ttl()

    with _cache_lock:
        if not force and _cache_data is not None and (now - _cache_ts) < ttl:
            return _cache_data

        data = scan_repositories(CONFIG_PATH)
        _cache_data = data
        _cache_ts = now
        return data


def _repo_by_id(repo_id: str) -> dict[str, Any] | None:
    data = load_dashboard(force=False)
    for repo in data.get("repos", []):
        if repo.get("id") == repo_id:
            return repo
    return None


def _run_cmd(args: list[str], timeout: int = 60) -> dict[str, Any]:
    try:
        p = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return {
            "code": p.returncode,
            "stdout": p.stdout.strip(),
            "stderr": p.stderr.strip(),
            "output": (p.stdout + p.stderr).strip(),
        }
    except Exception as e:
        return {"code": 1, "stdout": "", "stderr": str(e), "output": str(e)}


def _repo_owner_name(repo: dict[str, Any]) -> tuple[str, str] | tuple[None, None]:
    owner = str(repo.get("owner", "")).strip()
    name = str(repo.get("name", "")).strip()
    if owner and name:
        return owner, name
    remote = str(repo.get("remote", "")).strip()
    parsed = parse_remote_owner_repo(remote)
    if not parsed:
        return None, None
    return parsed


def _github_token() -> str:
    return os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_TOKEN", "").strip()


def _github_request_json(method: str, url: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    token = _github_token()
    if not token:
        return 401, {"error": "missing GITHUB_TOKEN or GH_TOKEN"}

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "project-track/1.0",
        "Authorization": f"Bearer {token}",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = Request(url, headers=headers, method=method, data=data)
    try:
        with urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except HTTPError as e:
        try:
            body = e.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {"error": str(e)}
        return e.code, parsed
    except Exception as e:
        return 500, {"error": str(e)}


def _repo_todo_path(repo_path: str) -> Path:
    return Path(repo_path) / "TODO.md"


def _read_repo_todos(repo_path: str) -> list[dict[str, Any]]:
    todo_path = _repo_todo_path(repo_path)
    if not todo_path.is_file():
        return []
    lines = todo_path.read_text(encoding="utf-8", errors="replace").splitlines()
    todos: list[dict[str, Any]] = []
    todo_idx = 0
    for line_no, line in enumerate(lines, start=1):
        m = TODO_RE.match(line)
        if not m:
            continue
        todos.append(
            {
                "index": todo_idx,
                "line_no": line_no,
                "done": m.group(1).lower() == "x",
                "text": m.group(2).strip(),
            }
        )
        todo_idx += 1
    return todos


def _append_repo_todo(repo_path: str, text: str) -> dict[str, Any]:
    todo_path = _repo_todo_path(repo_path)
    if not todo_path.exists():
        todo_path.write_text("# TODO\n\n", encoding="utf-8")
    with todo_path.open("a", encoding="utf-8") as f:
        f.write(f"- [ ] {text.strip()}\n")
    return {"todo_path": str(todo_path)}


def _update_repo_todo(repo_path: str, index: int, done: bool | None, text: str | None) -> dict[str, Any]:
    todo_path = _repo_todo_path(repo_path)
    if not todo_path.is_file():
        return {"ok": False, "error": "TODO.md not found"}
    lines = todo_path.read_text(encoding="utf-8", errors="replace").splitlines()

    hit = -1
    for i, line in enumerate(lines):
        m = TODO_RE.match(line)
        if not m:
            continue
        hit += 1
        if hit != index:
            continue
        cur_done = m.group(1).lower() == "x"
        cur_text = m.group(2).strip()
        new_done = cur_done if done is None else bool(done)
        new_text = cur_text if text is None else text.strip()
        mark = "x" if new_done else " "
        lines[i] = f"- [{mark}] {new_text}"
        todo_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"ok": True, "todo_path": str(todo_path)}
    return {"ok": False, "error": f"todo index not found: {index}"}


def _git_commit_push(repo_path: str, message: str, push: bool) -> dict[str, Any]:
    add = _run_cmd(["git", "-C", repo_path, "add", "."])
    if add["code"] != 0:
        return {"ok": False, "step": "add", **add}

    commit = _run_cmd(["git", "-C", repo_path, "commit", "-m", message])
    if commit["code"] != 0 and "nothing to commit" not in commit["output"].lower():
        return {"ok": False, "step": "commit", **commit}

    result = {"ok": True, "add": add, "commit": commit}
    if push:
        push_res = _run_cmd(["git", "-C", repo_path, "push", "origin", "HEAD"], timeout=120)
        result["push"] = push_res
        if push_res["code"] != 0:
            result["ok"] = False
    return result


def _repo_details(repo: dict[str, Any]) -> dict[str, Any]:
    repo_path = str(repo.get("path", ""))
    recent_commits = []
    recent = _run_cmd(
        [
            "git",
            "-C",
            repo_path,
            "log",
            "-20",
            "--date=short",
            "--pretty=format:%ad|%h|%an|%s",
        ]
    )
    if recent["stdout"]:
        for line in recent["stdout"].splitlines():
            p = line.split("|", 3)
            if len(p) == 4:
                recent_commits.append({"date": p[0], "hash": p[1], "author": p[2], "subject": p[3]})

    last_hash = str(repo.get("status", {}).get("last_commit", {}).get("hash", "")).strip()
    last_files: list[str] = []
    if last_hash:
        files = _run_cmd(
            ["git", "-C", repo_path, "show", "--name-only", "--pretty=format:", last_hash]
        )
        if files["stdout"]:
            last_files = [x.strip() for x in files["stdout"].splitlines() if x.strip()]

    status = _run_cmd(["git", "-C", repo_path, "status", "--short"])
    todos = _read_repo_todos(repo_path)

    owner, name = _repo_owner_name(repo)
    gh_open: list[dict[str, Any]] = []
    gh_err = ""
    if owner and name:
        code, data = _github_request_json(
            "GET", f"https://api.github.com/repos/{owner}/{name}/issues?state=open&per_page=30"
        )
        if code == 200 and isinstance(data, list):
            for issue in data:
                if issue.get("pull_request"):
                    continue
                gh_open.append(
                    {
                        "number": issue.get("number"),
                        "title": issue.get("title"),
                        "state": issue.get("state"),
                        "url": issue.get("html_url"),
                        "created_at": issue.get("created_at"),
                    }
                )
        else:
            gh_err = data.get("error") or data.get("message", "")

    return {
        "repo": repo,
        "recent_commits": recent_commits,
        "last_commit_files": last_files,
        "open_issues": gh_open,
        "open_issues_error": gh_err,
        "todos": todos,
        "working_tree_short": status["stdout"].splitlines() if status["stdout"] else [],
    }


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/api/dashboard")
def api_dashboard():
    refresh = request.args.get("refresh", "0") == "1"
    try:
        data = load_dashboard(force=refresh)
        return jsonify(data)
    except Exception as e:
        return jsonify({"ok": False, "error": f"dashboard scan failed: {e}"}), 500


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "")
    try:
        data = load_dashboard(force=False)
        results = search_key_issues(data, q, limit=100)
        return jsonify({"query": q, "count": len(results), "results": results})
    except Exception as e:
        return jsonify({"query": q, "count": 0, "results": [], "error": str(e)}), 500


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    data = load_dashboard(force=True)
    return jsonify({
        "ok": True,
        "generated_at": data.get("generated_at"),
        "total_repos": data.get("summary", {}).get("total_repos", 0),
    })


@app.route("/api/config")
def api_config():
    cfg = _read_config_raw()
    manifest = _read_manifest(cfg)
    include = list(cfg.get("include_repos", []))
    overrides = dict(cfg.get("track_overrides", {}))
    for item in manifest.get("repos", []):
        if not isinstance(item, dict):
            continue
        if item.get("enabled", True) is False:
            continue
        p = str(item.get("path", "")).strip()
        if not p:
            continue
        if p not in include:
            include.append(p)
        t = str(item.get("track", "")).strip()
        if t:
            overrides[p] = t
    return jsonify({
        "owner": cfg.get("owner", ""),
        "scan_roots": cfg.get("scan_roots", []),
        "include_repos": include,
        "track_overrides": overrides,
        "repo_manifest_path": str(_manifest_path(cfg)),
        "repo_manifest": manifest,
        "track_options": sorted(TRACK_OPTIONS),
        "config_path": CONFIG_PATH,
    })


@app.route("/api/repos", methods=["POST"])
def api_add_repo():
    payload = request.get_json(silent=True) or {}
    raw_path = str(payload.get("path", "")).strip()
    raw_track = str(payload.get("track", "")).strip()

    if not raw_path:
        return jsonify({"ok": False, "error": "path is required"}), 400

    repo_path = os.path.abspath(os.path.expanduser(raw_path))
    if not Path(repo_path, ".git").is_dir():
        return jsonify({"ok": False, "error": f"not a git repo: {repo_path}"}), 400

    track = raw_track if raw_track in TRACK_OPTIONS else ""
    cfg = _read_config_raw()
    manifest = _read_manifest(cfg)

    repos = manifest.setdefault("repos", [])
    found = False
    for item in repos:
        if not isinstance(item, dict):
            continue
        if os.path.abspath(os.path.expanduser(str(item.get("path", "")))) != repo_path:
            continue
        item["path"] = repo_path
        item["enabled"] = True
        if track:
            item["track"] = track
        found = True
        break

    if not found:
        entry = {"path": repo_path, "enabled": True}
        if track:
            entry["track"] = track
        repos.append(entry)

    _write_manifest(cfg, manifest)
    _invalidate_cache()
    data = load_dashboard(force=True)
    return jsonify({
        "ok": True,
        "path": repo_path,
        "track": track,
        "total_repos": data.get("summary", {}).get("total_repos", 0),
    })


@app.route("/api/repos", methods=["DELETE"])
def api_remove_repo():
    payload = request.get_json(silent=True) or {}
    raw_path = str(payload.get("path", "")).strip()
    if not raw_path:
        return jsonify({"ok": False, "error": "path is required"}), 400

    repo_path = os.path.abspath(os.path.expanduser(raw_path))
    cfg = _read_config_raw()
    manifest = _read_manifest(cfg)
    repos = manifest.setdefault("repos", [])

    original_len = len(repos)
    kept = []
    for item in repos:
        if not isinstance(item, dict):
            continue
        p = os.path.abspath(os.path.expanduser(str(item.get("path", ""))))
        if p == repo_path:
            continue
        kept.append(item)
    changed = len(kept) != original_len
    if changed:
        manifest["repos"] = kept
        _write_manifest(cfg, manifest)
        _invalidate_cache()

    data = load_dashboard(force=True)
    return jsonify({
        "ok": True,
        "removed": changed,
        "path": repo_path,
        "total_repos": data.get("summary", {}).get("total_repos", 0),
    })


@app.route("/api/group/<track>")
def api_group(track: str):
    if track not in TRACK_OPTIONS:
        return jsonify({"ok": False, "error": f"invalid track: {track}"}), 400
    data = load_dashboard(force=False)
    repos = [r for r in data.get("repos", []) if r.get("track") == track]
    repos.sort(key=lambda x: (x.get("progress", {}).get("score", 0), x.get("commits", {}).get("last_30d", 0)), reverse=True)
    return jsonify(
        {
            "ok": True,
            "track": track,
            "label": data.get("trend", {}).get("labels_map", {}).get(track, track),
            "summary": data.get("track_summary", {}).get(track, {}),
            "repos": repos,
        }
    )


@app.route("/api/group/<track>/sync", methods=["POST"])
def api_group_sync(track: str):
    if track not in TRACK_OPTIONS:
        return jsonify({"ok": False, "error": f"invalid track: {track}"}), 400
    data = load_dashboard(force=False)
    repos = [r for r in data.get("repos", []) if r.get("track") == track]
    results = []
    for repo in repos:
        p = repo.get("path", "")
        res = _run_cmd(["git", "-C", p, "pull", "--ff-only"], timeout=120)
        results.append({"id": repo.get("id"), "name": repo.get("display_name", repo.get("name")), "path": p, **res})
    _invalidate_cache()
    updated = load_dashboard(force=True)
    return jsonify(
        {
            "ok": True,
            "track": track,
            "results": results,
            "total_repos": updated.get("summary", {}).get("total_repos", 0),
        }
    )


@app.route("/api/repo/<repo_id>")
def api_repo_details(repo_id: str):
    repo = _repo_by_id(repo_id)
    if not repo:
        return jsonify({"ok": False, "error": "repo not found"}), 404
    return jsonify({"ok": True, **_repo_details(repo)})


@app.route("/api/repo/<repo_id>/sync", methods=["POST"])
def api_repo_sync(repo_id: str):
    repo = _repo_by_id(repo_id)
    if not repo:
        return jsonify({"ok": False, "error": "repo not found"}), 404
    res = _run_cmd(["git", "-C", repo["path"], "pull", "--ff-only"], timeout=120)
    _invalidate_cache()
    details = _repo_details(_repo_by_id(repo_id) or repo)
    return jsonify({"ok": res["code"] == 0, "sync": res, **details})


@app.route("/api/repo/<repo_id>/commit", methods=["POST"])
def api_repo_commit(repo_id: str):
    repo = _repo_by_id(repo_id)
    if not repo:
        return jsonify({"ok": False, "error": "repo not found"}), 404
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message", "")).strip()
    push = bool(payload.get("push", True))
    if not message:
        return jsonify({"ok": False, "error": "message is required"}), 400
    result = _git_commit_push(repo["path"], message, push)
    _invalidate_cache()
    details = _repo_details(_repo_by_id(repo_id) or repo)
    return jsonify({"ok": result.get("ok", False), "commit_result": result, **details})


@app.route("/api/repo/<repo_id>/issue", methods=["POST"])
def api_repo_issue(repo_id: str):
    repo = _repo_by_id(repo_id)
    if not repo:
        return jsonify({"ok": False, "error": "repo not found"}), 404
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title", "")).strip()
    body = str(payload.get("body", "")).strip()
    if not title:
        return jsonify({"ok": False, "error": "title is required"}), 400
    owner, name = _repo_owner_name(repo)
    if not owner or not name:
        return jsonify({"ok": False, "error": "unable to parse owner/repo"}), 400

    code, data = _github_request_json(
        "POST",
        f"https://api.github.com/repos/{owner}/{name}/issues",
        {"title": title, "body": body},
    )
    if code >= 300:
        return jsonify({"ok": False, "error": data.get("message") or data.get("error", "create issue failed"), "detail": data}), code

    details = _repo_details(repo)
    return jsonify({"ok": True, "issue": data, **details})


@app.route("/api/repo/<repo_id>/todo", methods=["POST"])
def api_repo_todo_add(repo_id: str):
    repo = _repo_by_id(repo_id)
    if not repo:
        return jsonify({"ok": False, "error": "repo not found"}), 404
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    do_commit = bool(payload.get("commit", False))
    do_push = bool(payload.get("push", False))
    if not text:
        return jsonify({"ok": False, "error": "text is required"}), 400
    wrote = _append_repo_todo(repo["path"], text)
    commit_result = None
    if do_commit:
        commit_result = _git_commit_push(repo["path"], f"chore(todo): add {text[:60]}", do_push)
    _invalidate_cache()
    details = _repo_details(_repo_by_id(repo_id) or repo)
    return jsonify({"ok": True, "write_result": wrote, "commit_result": commit_result, **details})


@app.route("/api/repo/<repo_id>/todo", methods=["PATCH"])
def api_repo_todo_update(repo_id: str):
    repo = _repo_by_id(repo_id)
    if not repo:
        return jsonify({"ok": False, "error": "repo not found"}), 404
    payload = request.get_json(silent=True) or {}
    if "index" not in payload:
        return jsonify({"ok": False, "error": "index is required"}), 400
    try:
        idx = int(payload.get("index"))
    except Exception:
        return jsonify({"ok": False, "error": "index must be integer"}), 400
    done = payload.get("done") if "done" in payload else None
    text = payload.get("text") if "text" in payload else None
    do_commit = bool(payload.get("commit", False))
    do_push = bool(payload.get("push", False))

    updated = _update_repo_todo(repo["path"], idx, done, text)
    if not updated.get("ok"):
        return jsonify(updated), 400

    commit_result = None
    if do_commit:
        commit_result = _git_commit_push(repo["path"], "chore(todo): update TODO item", do_push)
    _invalidate_cache()
    details = _repo_details(_repo_by_id(repo_id) or repo)
    return jsonify({"ok": True, "update_result": updated, "commit_result": commit_result, **details})


@app.route("/api/health")
def api_health():
    return jsonify({
        "ok": True,
        "config_path": CONFIG_PATH,
        "cwd": str(BASE_DIR),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5055, debug=False)
