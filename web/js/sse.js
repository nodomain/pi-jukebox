/**
 * Unified SSE connection — replaces most polling with server-pushed events.
 * @module sse
 */

import { state } from './state.js';
import { pollMaQueue, handleSnapcastStatus, handleAudioStatus, handleBtStatus } from './player.js';
import { handleStats } from './charts.js';
import { loadQueue } from './queue.js';

/** Update progress bar anchor from a time-update SSE event. */
function handleTimeUpdate(data) {
  if (data.elapsed_time != null) {
    state.npElapsed = data.elapsed_time;
    state.npElapsedAt = Date.now() / 1000;
  }
}

/** Connect to the unified SSE endpoint and handle all event types. */
export function connectSSE() {
  const es = new EventSource('/api/events');

  // MA WebSocket events (relayed through unified SSE)
  es.addEventListener('queue_updated', function () {
    pollMaQueue();
  });

  es.addEventListener('queue_items_updated', function () {
    if (state.queueVisible) loadQueue();
  });

  es.addEventListener('queue_time_updated', function (e) {
    try {
      handleTimeUpdate(JSON.parse(e.data));
    } catch (ex) {
      // Ignore parse errors
    }
  });

  // System stats (pushed every 3s by server)
  es.addEventListener('stats', function (e) {
    try {
      handleStats(JSON.parse(e.data));
    } catch (ex) {
      // Ignore
    }
  });

  // Bluetooth status (pushed every 9s)
  es.addEventListener('bt_status', function (e) {
    try {
      handleBtStatus(JSON.parse(e.data));
    } catch (ex) {
      // Ignore
    }
  });

  // Audio/PipeWire status (pushed every 9s)
  es.addEventListener('audio_status', function (e) {
    try {
      handleAudioStatus(JSON.parse(e.data));
    } catch (ex) {
      // Ignore
    }
  });

  // Snapcast status (pushed every 9s)
  es.addEventListener('snapcast_status', function (e) {
    try {
      handleSnapcastStatus(JSON.parse(e.data));
    } catch (ex) {
      // Ignore
    }
  });

  es.onerror = function () {
    es.close();
    setTimeout(connectSSE, 5000);
  };
}
