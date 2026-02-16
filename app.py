from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

from tracker.scanner import load_config, scan_repositories, search_key_issues

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
    return jsonify({
        "owner": cfg.get("owner", ""),
        "scan_roots": cfg.get("scan_roots", []),
        "include_repos": cfg.get("include_repos", []),
        "track_overrides": cfg.get("track_overrides", {}),
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

    include = cfg.setdefault("include_repos", [])
    if repo_path not in include:
        include.append(repo_path)

    overrides = cfg.setdefault("track_overrides", {})
    if track:
        overrides[repo_path] = track
    elif repo_path not in overrides:
        # Keep empty to allow auto-classification.
        pass

    _write_config_raw(cfg)
    _invalidate_cache()
    data = load_dashboard(force=True)
    return jsonify({
        "ok": True,
        "path": repo_path,
        "track": overrides.get(repo_path, ""),
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
    include = cfg.setdefault("include_repos", [])
    overrides = cfg.setdefault("track_overrides", {})

    changed = False
    if repo_path in include:
        include.remove(repo_path)
        changed = True
    if repo_path in overrides:
        del overrides[repo_path]
        changed = True

    if changed:
        _write_config_raw(cfg)
        _invalidate_cache()

    data = load_dashboard(force=True)
    return jsonify({
        "ok": True,
        "removed": changed,
        "path": repo_path,
        "total_repos": data.get("summary", {}).get("total_repos", 0),
    })


@app.route("/api/health")
def api_health():
    return jsonify({
        "ok": True,
        "config_path": CONFIG_PATH,
        "cwd": str(BASE_DIR),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5055, debug=False)
