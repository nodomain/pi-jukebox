/**
 * Entry point: imports all modules, initializes shared state, runs init.
 * @module main
 */

import { initTheme, toggleTheme } from './theme.js';
import { initCharts, pollStats, pollJitter } from './charts.js';
import {
  updateProgress, pollSnapcast, pollMaVolume, pollMaQueue,
  initVolumeSliders, initSeekBar, initSwipeGestures,
  snapControl, togglePlayPause,
  toggleFavorite, startSleepTimer, cancelSleepTimer, updateSleepTimerDisplay,
  pollAirplay,
} from './player.js';
import { toggleQueue, clearQueue, toggleShuffle, toggleRepeat, initQueueEvents } from './queue.js';
import { connectSSE } from './sse.js';
import { initFFT } from './fft.js';
import { pollBt, btScan, btDisconnect, svcAction, initSystemEvents } from './system.js';
import { initSearch, loadRecent, loadPlaylists, toggleRecent, togglePlaylists, playRecent, playPlaylist } from './browse.js';

// Re-export state for any module that still imports from main
export { state } from './state.js';

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
window.toggleFavorite = toggleFavorite;
window.showSleepMenu = showSleepMenu;
window.startSleepTimer = startSleepTimer;
window.cancelSleepTimer = cancelSleepTimer;
window.toggleRecent = toggleRecent;
window.togglePlaylists = togglePlaylists;
window.playRecent = playRecent;
window.playPlaylist = playPlaylist;

/** Show/hide sleep timer menu. */
function showSleepMenu() {
  const existing = document.getElementById('sleep-menu');
  if (existing) { existing.remove(); return; }
  const menu = document.createElement('div');
  menu.id = 'sleep-menu';
  menu.className = 'sleep-menu';
  menu.innerHTML = [15, 30, 45, 60, 90].map(m =>
    `<button onclick="startSleepTimer(${m}); document.getElementById('sleep-menu')?.remove()" class="secondary">${m}m</button>`
  ).join('') + `<button onclick="cancelSleepTimer(); document.getElementById('sleep-menu')?.remove()" class="secondary">Off</button>`;
  document.getElementById('btn-sleep').parentNode.appendChild(menu);
}

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
  initSearch();
  connectSSE();

  // Initial data fetch (SSE will take over after connection)
  pollStats();
  pollBt();
  pollSnapcast();
  pollMaVolume();
  pollMaQueue();
  pollJitter();
  pollAirplay();

  // Load browse sections
  loadRecent();
  loadPlaylists();

  // Only poll what SSE doesn't cover
  setInterval(pollMaVolume, 10000);
  setInterval(pollMaQueue, 10000);
  setInterval(pollJitter, 10000);
  setInterval(pollAirplay, 3000);

  // Progress bar + sleep timer display interpolation
  setInterval(() => {
    updateProgress();
    updateSleepTimerDisplay();
  }, 1000);
}

init();
