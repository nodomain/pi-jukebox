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
