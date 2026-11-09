"""The React app's JSON: search marks held songs, the library pages, and 'me' reads the cookie."""

from unittest.mock import MagicMock, patch

import pytest

from pikaraoke.lib.youtube_dl import SearchResult
from pikaraoke.routes.app_api import app_api_bp
from tests.conftest import make_route_app

HELD = SearchResult("Held Song", "https://youtu.be/aaaaaaaaaaa", "aaaaaaaaaaa", "Chan", "3:21")
MISSING = SearchResult("New Song", "https://youtu.be/zzzzzzzzzzz", "zzzzzzzzzzz", "Chan", "4:05")


@pytest.fixture
def app():
    return make_route_app(app_api_bp, [], admin=False)


@pytest.fixture
def k():
    k = MagicMock()
    k.song_manager.display_name_from_path.side_effect = lambda p: p.rsplit("/", 1)[-1].upper()
    k.singer_manager.get_favourite_paths.return_value = {"/s/b.mp4"}
    with patch("pikaraoke.routes.app_api.get_karaoke_instance", return_value=k):
        yield k


def test_search_quotes_karaoke_and_marks_library_songs(client, k):
    k.db.get_paths_by_youtube_ids.return_value = {"aaaaaaaaaaa": "/s/held.mp4"}
    with patch("pikaraoke.routes.app_api.get_search_results", return_value=[HELD, MISSING]) as s:
        body = client.get("/api/app/search?q=queen").get_json()
    s.assert_called_once_with('queen "karaoke"')
    assert [r["library_path"] for r in body["results"]] == ["/s/held.mp4", None]


def test_search_non_karaoke_passes_the_term_as_is(client, k):
    k.db.get_paths_by_youtube_ids.return_value = {}
    with patch("pikaraoke.routes.app_api.get_search_results", return_value=[]) as s:
        client.get("/api/app/search?q=queen&non_karaoke=true")
    s.assert_called_once_with("queen")


def test_library_pages_and_stars_for_the_cookie_singer(client, k):
    k.song_manager.songs = ["/s/a.mp4", "/s/b.mp4", "/s/c.mp4"]
    client.set_cookie("user", "Ana")
    body = client.get("/api/app/library?offset=1&limit=1").get_json()
    assert body["total"] == 3
    assert body["songs"] == [{"path": "/s/b.mp4", "title": "B.MP4", "favourite": True}]
    k.singer_manager.get_favourite_paths.assert_called_with("Ana")


def test_me_without_a_name_is_empty(client, k):
    assert client.get("/api/app/me").get_json() == {"name": None, "favourites": [], "recent": []}


def test_me_lists_recent_songs_once_and_skips_deleted_ones(client, k):
    k.play_history.get_plays.return_value = [
        {"file_path": "/s/a.mp4", "played_at": "2"},
        {"file_path": None, "played_at": "1"},
        {"file_path": "/s/a.mp4", "played_at": "0"},
    ]
    client.set_cookie("user", "Ana")
    body = client.get("/api/app/me").get_json()
    assert [s["path"] for s in body["recent"]] == ["/s/a.mp4"]
    assert [s["path"] for s in body["favourites"]] == ["/s/b.mp4"]


def test_popular_drops_songs_no_longer_in_the_library(client, k):
    k.play_history.get_top_songs.return_value = [
        {"file_path": "/s/a.mp4", "play_count": 5},
        {"file_path": None, "play_count": 4},
    ]
    body = client.get("/api/app/popular").get_json()
    assert body["songs"] == [{"path": "/s/a.mp4", "title": "A.MP4", "favourite": False, "plays": 5}]
