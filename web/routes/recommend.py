"""AI-powered music recommendations for Jukebox Pi.

Hybrid approach: Last.fm provides similar tracks for the currently playing
song, then an LLM (via OpenRouter) curates and enriches the suggestions
based on mood/context.  Results are validated against the Music Assistant
library so only playable tracks are returned.

Scrobbling is handled by the Music Assistant Last.fm plugin, not here.

Endpoints:
    POST /api/recommend  — get recommendations for the current track
"""

import json
import logging
import os
import urllib.request
import urllib.error

from flask import Blueprint, Response, jsonify, request  # pylint: disable=import-error

from helpers import run  # pylint: disable=import-error

recommend_bp = Blueprint("recommend", __name__)
log = logging.getLogger(__name__)

SNAPCAST_SERVER = os.environ.get("SNAPCAST_SERVER", "192.168.10.250")
MA_TOKEN = os.environ.get("MA_TOKEN", "")
LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get(
    "OPENROUTER_MODEL", "google/gemini-3.1-flash-lite-preview"
)


# ---------------------------------------------------------------------------
# Last.fm helpers
# ---------------------------------------------------------------------------

def _lastfm_similar(artist, track, limit=20):
    """Fetch similar tracks from Last.fm.

    Args:
        artist: Artist name.
        track: Track title.
        limit: Max results.

    Returns:
        List of dicts with 'artist' and 'name' keys.
    """
    if not LASTFM_API_KEY:
        return []
    try:
        url = (
            "https://ws.audioscrobbler.com/2.0/"
            f"?method=track.getsimilar"
            f"&artist={urllib.request.quote(artist)}"
            f"&track={urllib.request.quote(track)}"
            f"&api_key={LASTFM_API_KEY}"
            f"&limit={limit}"
            f"&format=json"
        )
        req = urllib.request.Request(
            url, headers={"User-Agent": "JukeboxPi/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        tracks = data.get("similartracks", {}).get("track", [])
        return [
            {"artist": t["artist"]["name"], "name": t["name"]}
            for t in tracks
            if isinstance(t, dict) and t.get("artist")
        ]
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("Last.fm similar failed: %s", exc)
        return []


def _lastfm_similar_artists(artist, limit=10):
    """Fetch similar artists from Last.fm.

    Args:
        artist: Artist name.
        limit: Max results.

    Returns:
        List of artist name strings.
    """
    if not LASTFM_API_KEY:
        return []
    try:
        url = (
            "https://ws.audioscrobbler.com/2.0/"
            f"?method=artist.getsimilar"
            f"&artist={urllib.request.quote(artist)}"
            f"&api_key={LASTFM_API_KEY}"
            f"&limit={limit}"
            f"&format=json"
        )
        req = urllib.request.Request(
            url, headers={"User-Agent": "JukeboxPi/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        artists = data.get("similarartists", {}).get("artist", [])
        return [
            a["name"] for a in artists
            if isinstance(a, dict) and a.get("name")
        ]
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("Last.fm similar artists failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# LLM helper (OpenRouter)
# ---------------------------------------------------------------------------

def _llm_curate(artist, track, similar_tracks, similar_artists, mood=""):
    """Ask an LLM to curate recommendations from Last.fm data.

    Args:
        artist: Current artist.
        track: Current track title.
        similar_tracks: List of dicts from Last.fm.
        similar_artists: List of artist names from Last.fm.
        mood: Optional user-provided mood/context string.

    Returns:
        List of dicts with 'artist' and 'name' keys (up to 10).
    """
    if not OPENROUTER_API_KEY:
        return similar_tracks[:10]

    lastfm_list = "\n".join(
        f"- {t['artist']} — {t['name']}" for t in similar_tracks[:20]
    )
    artist_list = ", ".join(similar_artists[:10])
    mood_line = f"\nUser request (may be in any language): {mood}" if mood else ""

    prompt = (
        f'I\'m listening to "{track}" by {artist}.{mood_line}\n\n'
        f"Here are similar tracks from Last.fm:\n{lastfm_list}\n\n"
        f"Similar artists: {artist_list}\n\n"
        "Pick the 10 best recommendations from the list above. "
        "You may also suggest up to 3 additional tracks NOT in the "
        "list that fit the vibe — but only well-known, real songs.\n\n"
        "IMPORTANT: Strongly prefer English-language tracks. "
        "Avoid German Schlager, Volksmusik, or non-English tracks "
        "unless the user explicitly asks for them.\n\n"
        "If the user wrote a request above, treat it as a free-text "
        "description of what they want to hear. Interpret it creatively "
        "— it could be a mood, a situation, a genre, or anything. "
        "Respond with tracks that match their intent.\n\n"
        "Return ONLY a JSON array, no markdown, no explanation. "
        'Each element: {"artist": "...", "name": "..."}'
    )

    try:
        payload = json.dumps({
            "model": OPENROUTER_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a music recommendation assistant. "
                        "Return only valid JSON arrays."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 800,
        }).encode()
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/nodomain/pi-jukebox",
                "X-Title": "Jukebox Pi",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())

        content = result["choices"][0]["message"]["content"].strip()
        # Strip markdown fences if present
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        tracks = json.loads(content)
        if isinstance(tracks, list):
            return [
                {"artist": t["artist"], "name": t["name"]}
                for t in tracks
                if isinstance(t, dict) and t.get("artist") and t.get("name")
            ][:10]
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("LLM curate failed: %s", exc)

    return similar_tracks[:10]


# ---------------------------------------------------------------------------
# MA search helper
# ---------------------------------------------------------------------------

def _ma_search(query, limit=3):
    """Search Music Assistant for a track.

    Args:
        query: Search string (e.g. "artist - track").
        limit: Max results.

    Returns:
        List of dicts with name, artist, uri, duration, image_url.
    """
    payload = json.dumps({
        "message_id": "rec",
        "command": "music/search",
        "args": {
            "search_query": query,
            "media_types": ["track"],
            "limit": limit,
        },
    })
    raw = run(
        f"curl -s -m 5 'http://{SNAPCAST_SERVER}:8095/api' "
        f"-H 'Content-Type: application/json' "
        f"-H 'Authorization: Bearer {MA_TOKEN}' "
        f"-d '{payload}'",
        timeout=7,
    )
    if not raw:
        return []
    try:
        data = json.loads(raw)
        result = data.get("result", data) if isinstance(data, dict) else data
        if not isinstance(result, dict):
            return []
        tracks = result.get("tracks", [])
        out = []
        for item in tracks[:limit]:
            artists = item.get("artists") or []
            artist_name = ", ".join(a.get("name", "") for a in artists)
            images = (item.get("metadata") or {}).get("images") or []
            thumb = ""
            for img in images:
                if img.get("path"):
                    thumb = img["path"]
                    break
            out.append({
                "name": item.get("name", ""),
                "artist": artist_name,
                "uri": item.get("uri", ""),
                "duration": item.get("duration", 0),
                "image_url": thumb,
            })
        return out
    except (json.JSONDecodeError, TypeError):
        return []


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@recommend_bp.route("/api/recommend", methods=["POST"])
def recommend():
    """Stream AI-curated recommendations as Server-Sent Events.

    Sends progress updates as they happen so the UI feels responsive:
      event: status   — progress text ("Fetching similar tracks...")
      event: track    — a validated track (JSON object)
      event: done     — final event

    Request JSON:
        artist (str): Current artist name.
        track (str): Current track title.
        mood (str, optional): User mood/context hint.
    """
    body = request.json or {}
    artist = body.get("artist", "").strip()
    track = body.get("track", "").strip()
    mood = body.get("mood", "").strip()

    if not artist or not track:
        return jsonify({"error": "Missing artist or track"}), 400

    def generate():
        yield _sse("status", "Fetching similar tracks from Last.fm...")

        similar_tracks = _lastfm_similar(artist, track)
        similar_artists = _lastfm_similar_artists(artist)
        count = len(similar_tracks)
        yield _sse("status", f"Found {count} similar tracks")

        # LLM curation
        source = "lastfm"
        if OPENROUTER_API_KEY:
            yield _sse("status", "AI is curating recommendations...")
            curated = _llm_curate(
                artist, track, similar_tracks, similar_artists, mood,
            )
            source = "lastfm+llm" if similar_tracks else "llm"
        else:
            curated = similar_tracks[:10]

        yield _sse(
            "status",
            f"Checking {len(curated)} tracks in your library...",
        )

        # Validate against MA — stream each match immediately
        seen = set()
        found = 0
        for i, rec in enumerate(curated):
            query = f"{rec['artist']} {rec['name']}"
            ma_results = _ma_search(query, limit=1)
            if ma_results:
                match = ma_results[0]
                key = match["uri"]
                if key not in seen:
                    seen.add(key)
                    match["source"] = source
                    match["suggested_artist"] = rec["artist"]
                    match["suggested_name"] = rec["name"]
                    found += 1
                    yield _sse("track", match)
            yield _sse(
                "status",
                f"Checking {len(curated)} tracks in your library... "
                f"({i + 1}/{len(curated)}, {found} found)",
            )

        yield _sse("done", {"total": found})

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event, data):
    """Format a single SSE message."""
    payload = json.dumps(data) if not isinstance(data, str) else json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


# ---------------------------------------------------------------------------
# Auto-recommend: "Don't Stop the Music" mode
# ---------------------------------------------------------------------------

def _ma_recent_tracks(limit=10):
    """Fetch recently played tracks from MA.

    Returns:
        List of dicts with 'artist' and 'name' keys.
    """
    payload = json.dumps({
        "message_id": "auto",
        "command": "music/recently_played_items",
        "args": {"limit": limit, "media_types": ["track"]},
    })
    raw = run(
        f"curl -s -m 5 'http://{SNAPCAST_SERVER}:8095/api' "
        f"-H 'Content-Type: application/json' "
        f"-H 'Authorization: Bearer {MA_TOKEN}' "
        f"-d '{payload}'",
        timeout=7,
    )
    if not raw:
        return []
    try:
        data = json.loads(raw)
        result = data.get("result", data) if isinstance(data, dict) else data
        items = result if isinstance(result, list) else []
        out = []
        for item in items[:limit]:
            media = item if "name" in item else item.get("media_item", item)
            artists = media.get("artists") or []
            artist = ", ".join(a.get("name", "") for a in artists)
            name = media.get("name", "")
            if artist and name:
                out.append({"artist": artist, "name": name})
        return out
    except (json.JSONDecodeError, TypeError):
        return []


def _llm_auto_recommend(history, similar_pool, similar_artists, exclude):
    """Ask LLM to pick tracks based on listening history.

    Args:
        history: List of recently played dicts (artist, name).
        similar_pool: Aggregated Last.fm similar tracks.
        similar_artists: Aggregated similar artist names.
        exclude: Set of "artist|name" strings to avoid repeats.

    Returns:
        List of dicts with 'artist' and 'name' keys (5-8 tracks).
    """
    if not OPENROUTER_API_KEY:
        # No LLM — return random similar tracks not in exclude
        return [
            t for t in similar_pool
            if f"{t['artist']}|{t['name']}" not in exclude
        ][:5]

    history_list = "\n".join(
        f"- {t['artist']} — {t['name']}" for t in history[:10]
    )
    pool_list = "\n".join(
        f"- {t['artist']} — {t['name']}" for t in similar_pool[:30]
    )
    artist_list = ", ".join(similar_artists[:15])
    exclude_list = "\n".join(
        f"- {e.replace('|', ' — ')}" for e in list(exclude)[:20]
    )

    prompt = (
        "I'm in 'endless radio' mode. Here's what I've been listening to "
        "recently:\n"
        f"{history_list}\n\n"
        f"Similar tracks from Last.fm:\n{pool_list}\n\n"
        f"Similar artists: {artist_list}\n\n"
        "DO NOT suggest any of these (already played/queued):\n"
        f"{exclude_list}\n\n"
        "Pick 5 to 8 tracks that continue this vibe naturally. "
        "Mix picks from the Last.fm list with your own suggestions. "
        "Prefer English-language tracks. Avoid German Schlager.\n\n"
        "Return ONLY a JSON array. "
        'Each element: {"artist": "...", "name": "..."}'
    )

    try:
        payload = json.dumps({
            "model": OPENROUTER_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a music DJ assistant for an endless "
                        "radio mode. Return only valid JSON arrays."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.8,
            "max_tokens": 600,
        }).encode()
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/nodomain/pi-jukebox",
                "X-Title": "Jukebox Pi",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())

        content = result["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        tracks = json.loads(content)
        if isinstance(tracks, list):
            return [
                {"artist": t["artist"], "name": t["name"]}
                for t in tracks
                if isinstance(t, dict) and t.get("artist") and t.get("name")
                and f"{t['artist']}|{t['name']}" not in exclude
            ][:8]
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("LLM auto-recommend failed: %s", exc)

    return [
        t for t in similar_pool
        if f"{t['artist']}|{t['name']}" not in exclude
    ][:5]


@recommend_bp.route("/api/recommend/auto", methods=["POST"])
def recommend_auto():
    """Auto-fill queue based on listening history.

    Called by the frontend when the queue is running low in
    "Don't Stop the Music" mode.

    Request JSON:
        queue_id (str): MA queue ID to add tracks to.
        exclude (list, optional): URIs already in queue to avoid.

    Returns:
        JSON with 'added' count and 'tracks' list.
    """
    body = request.json or {}
    queue_id = body.get("queue_id", "")
    exclude_uris = set(body.get("exclude", []))

    if not queue_id:
        return jsonify({"error": "Missing queue_id"}), 400

    # 1. Get recently played tracks
    history = _ma_recent_tracks(10)
    if not history:
        return jsonify({"error": "No listening history"}), 400

    # 2. Aggregate Last.fm similar tracks from the last few played
    similar_pool = []
    similar_artists_pool = []
    seen_similar = set()
    for h in history[:5]:
        for t in _lastfm_similar(h["artist"], h["name"], limit=10):
            key = f"{t['artist']}|{t['name']}"
            if key not in seen_similar:
                seen_similar.add(key)
                similar_pool.append(t)
        for a in _lastfm_similar_artists(h["artist"], limit=5):
            if a not in similar_artists_pool:
                similar_artists_pool.append(a)

    # 3. Build exclude set (history + current queue URIs)
    exclude_keys = set()
    for h in history:
        exclude_keys.add(f"{h['artist']}|{h['name']}")

    # 4. LLM picks the best tracks
    curated = _llm_auto_recommend(
        history, similar_pool, similar_artists_pool, exclude_keys,
    )

    # 5. Validate against MA and add to queue
    added = []
    for rec in curated:
        query = f"{rec['artist']} {rec['name']}"
        ma_results = _ma_search(query, limit=1)
        if ma_results:
            match = ma_results[0]
            if match["uri"] in exclude_uris:
                continue
            exclude_uris.add(match["uri"])
            # Add to MA queue
            _ma_play(queue_id, match["uri"])
            added.append(match)

    return jsonify({"added": len(added), "tracks": added})


def _ma_play(queue_id, uri):
    """Add a track URI to the MA queue."""
    payload = json.dumps({
        "message_id": "auto",
        "command": "player_queues/play_media",
        "args": {
            "queue_id": queue_id,
            "media": [uri],
            "option": "add",
        },
    })
    run(
        f"curl -s -m 5 'http://{SNAPCAST_SERVER}:8095/api' "
        f"-H 'Content-Type: application/json' "
        f"-H 'Authorization: Bearer {MA_TOKEN}' "
        f"-d '{payload}'",
        timeout=7,
    )
