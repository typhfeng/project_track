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


@app.route("/api/health")
def api_health():
    return jsonify({
        "ok": True,
        "config_path": CONFIG_PATH,
        "cwd": str(BASE_DIR),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5055, debug=False)
