/**
 * Fetch wrappers for all Jukebox Pi API endpoints.
 * @module api
 */

/**
 * Fetch system stats.
 * @returns {Promise<Object>}
 */
export function fetchStats() {
  return fetch('/api/stats').then(r => r.json());
}

/**
 * Fetch Bluetooth status.
 * @returns {Promise<Object>}
 */
export function fetchBtStatus() {
  return fetch('/api/bt/status').then(r => r.json());
}

/**
 * Scan for Bluetooth devices.
 * @returns {Promise<Object>}
 */
export function fetchBtScan() {
  return fetch('/api/bt/scan', { method: 'POST' }).then(r => r.json());
}

/**
 * Connect to a Bluetooth device.
 * @param {string} mac
 * @returns {Promise<Object>}
 */
export function fetchBtConnect(mac) {
  return fetch('/api/bt/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mac }),
  }).then(r => r.json());
}

/**
 * Disconnect a Bluetooth device.
 * @param {string} mac
 * @returns {Promise<Object>}
 */
export function fetchBtDisconnect(mac) {
  return fetch('/api/bt/disconnect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mac }),
  }).then(r => r.json());
}

/**
 * Fetch PipeWire audio status.
 * @returns {Promise<Object>}
 */
export function fetchAudioStatus() {
  return fetch('/api/audio/status').then(r => r.json());
}

/**
 * Set PipeWire default sink volume.
 * @param {number} volume - 0.0 to 1.5
 * @returns {Promise<Object>}
 */
export function setAudioVolume(volume) {
  return fetch('/api/audio/volume', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ volume }),
  }).then(r => r.json());
}

/**
 * Fetch Snapcast server status.
 * @returns {Promise<Object>}
 */
export function fetchSnapcastStatus() {
  return fetch('/api/snapcast/status').then(r => r.json());
}

/**
 * Send a Snapcast playback control command.
 * @param {string} action - play, pause, next, previous, seek
 * @param {string} streamId
 * @param {Object} [extra] - additional params (e.g. position for seek)
 * @returns {Promise<Object>}
 */
export function snapcastControl(action, streamId, extra = {}) {
  return fetch('/api/snapcast/control', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, streamId, ...extra }),
  }).then(r => r.json());
}

/**
 * Fetch Snapcast buffer jitter data.
 * @returns {Promise<Object>}
 */
export function fetchSnapcastJitter() {
  return fetch('/api/snapcast/jitter').then(r => r.json());
}

/**
 * Fetch MA player volume.
 * @returns {Promise<Object>}
 */
export function fetchMaVolume() {
  return fetch('/api/ma/volume').then(r => r.json());
}

/**
 * Set MA player volume.
 * @param {string} playerId
 * @param {number} volume - 0 to 100
 * @returns {Promise<Object>}
 */
export function setMaVolume(playerId, volume) {
  return fetch('/api/ma/volume', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ player_id: playerId, volume }),
  }).then(r => r.json());
}

/**
 * Fetch active MA queue (track position, metadata).
 * @returns {Promise<Object>}
 */
export function fetchMaQueue() {
  return fetch('/api/ma/queue').then(r => r.json());
}

/**
 * Fetch MA queue items list.
 * @param {string} queueId
 * @param {number} [limit=100]
 * @returns {Promise<Object>}
 */
export function fetchMaQueueItems(queueId, limit = 100) {
  return fetch(`/api/ma/queue/items?queue_id=${queueId}&limit=${limit}`).then(r => r.json());
}

/**
 * Perform a queue action (delete, move, play_index, clear, shuffle, repeat).
 * @param {Object} body
 * @returns {Promise<Object>}
 */
export function maQueueAction(body) {
  return fetch('/api/ma/queue/action', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(r => r.json());
}

/**
 * Perform a service action (restart-snapclient, restart-bt, reboot).
 * @param {string} action
 * @returns {Promise<Response>}
 */
export function serviceAction(action) {
  return fetch(`/api/service/${action}`, { method: 'POST' });
}


// --- New features ---

/** Add track URI to MA favorites. */
export function maFavorite(uri) {
  return fetch('/api/ma/favorite', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ uri }),
  }).then(r => r.json());
}

/** Fetch recently played items. */
export function fetchRecentlyPlayed(limit = 20) {
  return fetch(`/api/ma/recent?limit=${limit}`).then(r => r.json());
}

/** Search MA library. */
export function maSearch(query, types = 'track,album,playlist', limit = 20) {
  return fetch(`/api/ma/search?q=${encodeURIComponent(query)}&types=${types}&limit=${limit}`).then(r => r.json());
}

/** Play a media URI on a queue. */
export function maPlayMedia(uri, queueId, option = 'play') {
  return fetch('/api/ma/play', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ uri, queue_id: queueId, option }),
  }).then(r => r.json());
}

/** Fetch MA playlists. */
export function fetchPlaylists() {
  return fetch('/api/ma/playlists').then(r => r.json());
}

/** Set Snapcast client volume. */
export function setSnapcastClientVolume(clientId, volume, muted = false) {
  return fetch('/api/snapcast/client/volume', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id: clientId, volume, muted }),
  }).then(r => r.json());
}

/** Set Snapcast client latency. */
export function setSnapcastClientLatency(clientId, latency) {
  return fetch('/api/snapcast/client/latency', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id: clientId, latency }),
  }).then(r => r.json());
}


/** Fetch album tracks. */
export function fetchAlbumTracks(itemId, provider = 'library') {
  return fetch(`/api/ma/album/tracks?item_id=${encodeURIComponent(itemId)}&provider=${encodeURIComponent(provider)}`).then(r => r.json());
}


/** Fetch playlist tracks. */
export function fetchPlaylistTracks(itemId, provider = 'builtin') {
  return fetch(`/api/ma/playlist/tracks?item_id=${encodeURIComponent(itemId)}&provider=${encodeURIComponent(provider)}`).then(r => r.json());
}


/** Fetch AirPlay status. */
export function fetchAirplayStatus() {
  return fetch('/api/airplay/status').then(r => r.json());
}


/** Fetch lyrics separately (non-blocking). */
export function fetchLyrics(artist, title) {
  return fetch(`/api/ma/lyrics?artist=${encodeURIComponent(artist)}&title=${encodeURIComponent(title)}`).then(r => r.json());
}

/** Fetch Spotify Connect status. */
export function fetchSpotifyStatus() {
  return fetch('/api/spotify/status').then(r => r.json());
}

/** Control MA playback directly (play/pause/next/previous/seek). */
export function maControl(action, queueId, extra = {}) {
  return fetch('/api/ma/control', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, queue_id: queueId, ...extra }),
  }).then(r => r.json());
}
