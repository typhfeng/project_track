from __future__ import annotations

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


@app.route("/api/health")
def api_health():
    return jsonify({
        "ok": True,
        "config_path": CONFIG_PATH,
        "cwd": str(BASE_DIR),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5055, debug=False)
