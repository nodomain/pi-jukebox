/**
 * Entry point: imports all modules, initializes shared state, runs init.
 * @module main
 */

import { initTheme, toggleTheme } from './theme.js';
import { initCharts, pollStats, pollJitter, handleStats } from './charts.js';
import {
  updateProgress, pollSnapcast, pollMaVolume, pollMaQueue,
  initVolumeSliders, initSeekBar, initSwipeGestures,
  snapControl, togglePlayPause,
  handleSnapcastStatus, handleAudioStatus, handleBtStatus,
} from './player.js';
import { toggleQueue, clearQueue, toggleShuffle, toggleRepeat, initQueueEvents } from './queue.js';
import { connectSSE } from './sse.js';
import { initFFT } from './fft.js';
import { pollBt, btScan, btDisconnect, svcAction, initSystemEvents } from './system.js';

/**
 * Shared application state.
 * Exported so all modules can read/write the same object.
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

// Expose action functions to inline onclick handlers in the HTML template
window.toggleTheme = toggleTheme;
window.snapControl = snapControl;
window.togglePlayPause = togglePlayPause;
window.btScan = btScan;
window.btDisconnect = btDisconnect;
window.svcAction = svcAction;
window.toggleQueue = toggleQueue;
window.clearQueue = clearQueue;
window.toggleShuffle = toggleShuffle;
window.toggleRepeat = toggleRepeat;

/** Initialize everything once the DOM is ready. */
function init() {
  initTheme();
  initCharts();
  initVolumeSliders();
  initSeekBar();
  initSwipeGestures();
  initQueueEvents();
  initSystemEvents();
  initFFT();
  connectSSE();

  // Initial data fetch (SSE will take over after connection)
  pollStats();
  pollBt();
  pollSnapcast();
  pollMaVolume();
  pollMaQueue();
  pollJitter();

  // Only poll what SSE doesn't cover
  setInterval(pollMaVolume, 10000);
  setInterval(pollJitter, 10000);
  setInterval(pollMaQueue, 10000);
  setInterval(pollJitter, 10000);
  setInterval(pollMaQueue, 10000);

  // Progress bar interpolation
  setInterval(updateProgress, 1000);
}

init();
