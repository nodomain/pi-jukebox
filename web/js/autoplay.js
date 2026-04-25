/**
 * "Don't Stop the Music" mode — uses MA's native feature.
 * @module autoplay
 */

import { state } from './state.js';
import { maQueueAction } from './api.js';

/** Toggle Don't Stop the Music via MA API. */
export function toggleAutoplay() {
  state.autoplayEnabled = !state.autoplayEnabled;
  const btn = document.getElementById('btn-autoplay');
  if (!btn) return;

  if (state.autoplayEnabled) {
    btn.style.opacity = '1';
    btn.title = "Don't Stop the Music: ON";
  } else {
    btn.style.opacity = '0.3';
    btn.title = "Don't Stop the Music: OFF";
  }

  // Use MA's native dont_stop_the_music feature
  if (state.currentQueueId) {
    maQueueAction({
      action: 'dont_stop_the_music',
      queue_id: state.currentQueueId,
      enabled: state.autoplayEnabled,
    });
  }
}

/** Initialize autoplay state from queue data. */
export function initAutoplay() {
  state.autoplayEnabled = false;
  const btn = document.getElementById('btn-autoplay');
  if (btn) btn.style.opacity = '0.3';
}

/** Update autoplay button state from queue data (called by pollMaQueue). */
export function updateAutoplayState(dontStopEnabled) {
  state.autoplayEnabled = !!dontStopEnabled;
  const btn = document.getElementById('btn-autoplay');
  if (btn) {
    btn.style.opacity = state.autoplayEnabled ? '1' : '0.3';
    btn.title = state.autoplayEnabled
      ? "Don't Stop the Music: ON"
      : "Don't Stop the Music: OFF";
  }
}
