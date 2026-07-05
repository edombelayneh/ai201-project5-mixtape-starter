# Mixtape — Codebase Map

Mixtape is a Flask app where people share songs, build collaborative playlists, and see what their friends are listening to. It's organized in layers: routes handle HTTP, services hold the actual logic, and models define the database.

`app.py` is the entry point — it builds the Flask app, connects SQLite, and wires up the four route groups. `models.py` defines the data: users (with friend links and listening streaks), songs, tags, playlists, ratings, notifications, and listening events, plus the join tables that connect them. `seed_data.py` fills the database with sample data to test against.

The `routes/` - each file just reads the request, calls a service, and returns JSON. There are four groups: songs (search, rate, listen), playlists (create, view, add songs), users (profile, streak, notifications), and feed (what friends are playing).

The real work lives in `services/`:

- **feed_service** builds the friend feeds — one shows who listened in the last 24 hours, the other is a running activity log.
- **notification_service** creates and reads notifications, and handles adding songs to playlists and rating them.
- **playlist_service** creates playlists and pulls their songs back in order.
- **search_service** searches songs by title or artist.
- **streak_service** records each listen and keeps the consecutive-day streak up to date.

`tests/` covers the playlist, search, and streak services with pytest.

## Bug Fixes

### Bug 1 — Playlists silently drop their last song

**Location:** `services/playlist_service.py`, `get_playlist_songs()`

**The bug:** The function queried all songs correctly but returned `songs[:-1]`, slicing off the last element. Every playlist came back missing its final track (highest `position`).

**Root cause:** The `[:-1]` slice discarded good data after a complete, correctly-ordered query — there was no ordering or filtering reason for it. A 5-song playlist returned 4; a 1-song playlist returned 0.

**Expected behavior:** Return every song in the playlist, in position order.

**How I reproduced it:** Seeded the database (`python seed_data.py`), which creates three playlists of 7 songs each. Hitting `GET /playlists/857c9f3d-e362-46f2-94c0-26efc3384ddc/songs` (the "Late Night Vibes" playlist) in the browser returned only 6 song objects instead of the 7 stored in the DB. Confirmed the true count by querying `playlist_entries` directly (7). The unit test `test_playlist_returns_all_songs` also failed with `assert 4 == 5` on a 5-song fixture.

**The fix:** Return all songs (`songs[:]`) instead of `songs[:-1]`. Re-running the endpoint now returns all 7, and the test passes.
