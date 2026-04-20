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
  npServerTime: 0,
};
