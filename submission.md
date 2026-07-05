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

### Bug 2 — Listening streaks reset on Sundays

**Location:** `services/streak_service.py`, `update_listening_streak()`

**The bug:** The consecutive-day branch was gated by an extra clause: `elif days_since_last == 1 and today.weekday() != 6:`. Since `weekday()` returns 6 for Sunday, any streak that continued onto a Sunday skipped the increment and fell into the `else`, which reset the streak to 1.

**Root cause:** The `and today.weekday() != 6` condition had nothing to do with streak logic. The docstring states the rule with no exceptions ("If the user listened yesterday: streak increments by 1"), so the day of the week should never matter. A user who listened Saturday and again Sunday had their streak wiped instead of extended.

**Expected behavior:** Listening on consecutive calendar days increments the streak by 1, regardless of which day of the week it is.

**How I reproduced it:** Today's date happened to be a Sunday, so I could trigger it against the real clock. I set user "nova" to `last_listened_at = Saturday` with `listening_streak = 5`, then recorded a listen for today via `POST /songs/<song_id>/listen` and read back `GET /users/<user_id>/streak`. The buggy version returned a streak of **1** (reset) instead of the expected **6**. The unit test `test_streak_increments_on_sunday` also failed with `assert 1 == 2` for a Saturday→Sunday sequence.

**The fix:** Remove the `and today.weekday() != 6` clause so the branch is simply `elif days_since_last == 1:`. After resetting nova back to the Saturday state and repeating the listen, the streak correctly incremented to **6**, and the test passes.

### Bug 3 — Adding a song to a playlist crashes, and duplicates report a false success

This bug had two parts, both in `services/notification_service.py`, `add_to_playlist()`.

**How I found it:** To test the app end-to-end as a real user, I had the AI assistant build an interactive browser test console (a single HTML page served by Flask at `/`, plus small read-only `/dev/` helper endpoints to populate dropdowns). The console lets me act as any seeded user and exercise every endpoint — search, listen, rate, view feeds/streaks/notifications, and add songs to playlists — while a response log shows the raw HTTP status and JSON for each action. Clicking the **"+ Playlist"** button is what surfaced this bug.

**What I observed in the console:**
1. Adding a song that was **not** already in a playlist failed with a client-side `SyntaxError: Unexpected token '<', "<!doctype "... is not valid JSON`. (The server was actually returning a 500 HTML error page, which the console tried to parse as JSON.)
2. Adding a song that was **already** in the playlist returned a success message ("Song added to playlist"), but the playlist's song count never changed on a later check.

**Root cause (part A — the crash):** The code added songs via the ORM relationship (`playlist.songs.append(song)`). The `playlist_entries` association table has two `NOT NULL` columns — `position` and `added_by` — that the relationship append doesn't populate, so the insert violated the `NOT NULL` constraint on `position` and raised `sqlite3.IntegrityError`, surfacing as a 500.

**Root cause (part B — the false success):** The `if song not in playlist.songs:` guard correctly skipped re-adding a duplicate, but the success return and the "notify the sharer" block below it ran **unconditionally**. So a duplicate add reported success *and* generated a phantom "X added your song" notification, even though nothing was added.

**Expected behavior:** A new song is appended at the next position with `added_by` recorded, and the sharer is notified. A song already in the playlist is left unchanged, with no notification and an honest "already in playlist" response.

**How I reproduced it (outside the console, to confirm root cause):** POSTed to `/playlists/857c9f3d-.../songs` (Late Night Vibes) with a song not in the playlist → got the `IntegrityError: NOT NULL constraint failed: playlist_entries.position` traceback. Then POSTed a song already in the playlist as a different user → response was `201 "Song added to playlist"`, the entry count stayed at 7, and the sharer's notification count went from 0 to 1 (the phantom notification).

**The fix:**
- Insert into `playlist_entries` explicitly, computing `position` as the current max position + 1 and passing `added_by`, instead of appending through the relationship.
- Check for an existing entry first and return early (a new `bool` return: `True` if added, `False` if already present) so the notification only fires on a genuine add.
- Update the route to return `201 "Song added to playlist"` when added and `200 "Song already in playlist"` otherwise.

After the fix: adding a new song to Late Night Vibes moved the count 7 → 8 (new song at position 8, sharer notified), and re-adding it returned `200 "Song already in playlist"` with the count and notification count unchanged. All 13 tests still pass.

### Bug 4 — Rating a song never notifies the sharer

**Location:** `services/notification_service.py`, `rate_song()`

**How I found it:** I set out to hunt specifically for notification problems using the test console, and had the AI assistant help trace the notification code paths. Grepping for `create_notification` showed it's called in exactly one place — `add_to_playlist` — and never in `rate_song`. I confirmed it in the console: acting as one user I rated another user's song (★ Rate), then switched the "Acting as" dropdown to the sharer and checked Notifications — nothing appeared.

**What's wrong:** `rate_song` saves the rating and returns without ever calling `create_notification`, so the song's original sharer is never told their song was rated.

**Why it's a bug (not just an unbuilt feature):** Three signals point to this being intended behavior that went missing:
1. The module's top docstring says "Notifications are generated when friends interact with a user's shared songs" — rating is exactly that kind of interaction.
2. `create_notification`'s own docstring lists `'song_rated'` as an example notification type, but that string appeared nowhere else in the codebase — a dangling reference to a notification that was supposed to exist.
3. It's inconsistent with `add_to_playlist`, which does notify the sharer on interaction.

**Expected behavior:** When a user rates another user's shared song, the sharer receives a `'song_rated'` notification (e.g. "darius rated your song 'Midnight Drive' 5 stars."). A user rating their own song should not self-notify, mirroring the `shared_by != added_by` guard in `add_to_playlist`. Per design decision, a notification fires on every rate action, including re-rating.

**How I reproduced it:** `POST /songs/<song_id>/rate` with darius rating nova's song "Midnight Drive" 5 stars → rating saved (201), but nova's notification count stayed unchanged (1 → 1).

**The fix:** Add a notification block at the end of `rate_song`, mirroring `add_to_playlist`: after the commit, if `song.shared_by != user_id`, create a `'song_rated'` notification for the sharer.

After the fix, verified all three cases: another user rating → sharer notified (1 → 2); the same user re-rating with a new score → notified again (2 → 3, per the every-action decision); the sharer rating their own song → no notification (stayed 3). Notification body reads "darius rated your song 'Midnight Drive' 3 stars." All 13 tests still pass.
