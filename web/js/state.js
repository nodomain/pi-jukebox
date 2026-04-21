/**
 * Shared application state.
 * Separate module to avoid circular imports.
 * @module state
 */

export const state = {
  currentStreamId: '',
  isPlaying: false,
  currentQueueId: '',
  queueVisible: false,
  lastImageUrl: '',
  currentShuffle: false,
  currentRepeat: 'off',
  maPlayerId: '',
  npDuration: 0,
  npElapsed: 0,
  npElapsedAt: 0,
  // Current track URI for favorites
  currentTrackUri: '',
  // Snapcast client ID (for volume/latency control)
  snapClientId: '',
  // Sleep timer ID (setTimeout handle)
  sleepTimerId: null,
  sleepTimerEnd: 0,
  // Timestamp (ms) until which play-state SSE updates should be ignored,
  // set after a user-initiated playback control action.
  playStateLockUntil: 0,
};
