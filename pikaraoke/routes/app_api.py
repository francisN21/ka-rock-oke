"""JSON for the Ka-Rock-oke React app, and the app itself at /app.

The original pages get search results, the library and a singer's songs rendered
into HTML; the app needs the same data as JSON. Everything here reads the existing
managers, so the two front ends always agree.
"""

from pathlib import Path

from flask import abort, jsonify, request, send_from_directory
from flask_smorest import Blueprint

from pikaraoke.lib.auth import public
from pikaraoke.lib.current_app import current_singer_name, get_karaoke_instance
from pikaraoke.lib.youtube_dl import get_search_results

app_api_bp = Blueprint("app_api", __name__)

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
LIBRARY_PAGE_MAX = 200


def _song(path: str, favourites: set[str]) -> dict:
    k = get_karaoke_instance()
    return {
        "path": path,
        "title": k.song_manager.display_name_from_path(path),
        "favourite": path in favourites,
    }


def _favourites() -> set[str]:
    name = current_singer_name()
    return get_karaoke_instance().singer_manager.get_favourite_paths(name) if name else set()


@app_api_bp.route("/api/app/search")
@public
def search():
    """YouTube results, each marked with its library path when already downloaded."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"results": []})
    # Same quoting as the search page: it keeps results to karaoke versions.
    query = q if request.args.get("non_karaoke") == "true" else f'{q} "karaoke"'
    results = get_search_results(query)
    matches = get_karaoke_instance().db.get_paths_by_youtube_ids([r.video_id for r in results])
    return jsonify(
        {
            "results": [
                {
                    "title": r.title,
                    "url": r.url,
                    "video_id": r.video_id,
                    "channel": r.channel,
                    "duration": r.duration,
                    "library_path": matches.get(r.video_id),
                }
                for r in results
            ]
        }
    )


@app_api_bp.route("/api/app/library")
@public
def library():
    """A page of downloaded songs, A to Z, optionally filtered by a search."""
    k = get_karaoke_instance()
    q = (request.args.get("q") or "").strip()
    songs = k.song_manager.search(q) if q else list(k.song_manager.songs)
    offset = max(0, request.args.get("offset", 0, type=int))
    limit = min(LIBRARY_PAGE_MAX, max(1, request.args.get("limit", 50, type=int)))
    favourites = _favourites()
    return jsonify(
        {
            "total": len(songs),
            "songs": [_song(p, favourites) for p in songs[offset : offset + limit]],
        }
    )


@app_api_bp.route("/api/app/popular")
@public
def popular():
    """The room's most-sung songs that are still in the library."""
    k = get_karaoke_instance()
    favourites = _favourites()
    rows = k.play_history.get_top_songs(limit=30)
    songs = [
        {**_song(r["file_path"], favourites), "plays": r["play_count"]}
        for r in rows
        if r["file_path"]
    ]
    return jsonify({"songs": songs[:12]})


@app_api_bp.route("/api/app/me")
@public
def me():
    """This device's singer: their starred songs and what they sang lately."""
    name = current_singer_name()
    if not name:
        return jsonify({"name": None, "favourites": [], "recent": []})
    k = get_karaoke_instance()
    favourites = _favourites()
    recent, seen = [], set()
    for play in k.play_history.get_plays(performer=name, limit=60):
        path = play.get("file_path")
        if path and path not in seen:
            seen.add(path)
            recent.append({**_song(path, favourites), "played_at": play.get("played_at")})
    return jsonify(
        {
            "name": name,
            "favourites": sorted(
                (_song(p, favourites) for p in favourites), key=lambda s: s["title"].lower()
            ),
            "recent": recent[:20],
        }
    )


@app_api_bp.route("/app/")
@public
def frontend_index():
    """The built React app."""
    return frontend("")


@app_api_bp.route("/app/<path:path>")
@public
def frontend(path: str):
    """App files; unknown paths fall back to index.html for client-side routing."""
    if not FRONTEND_DIST.is_dir():
        abort(404, "The app isn't built yet. Run: cd frontend && npm run build")
    if path and (FRONTEND_DIST / path).is_file():
        return send_from_directory(FRONTEND_DIST, path)
    return send_from_directory(FRONTEND_DIST, "index.html")
