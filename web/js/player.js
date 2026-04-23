/**
 * Now playing, playback controls, seek, swipe, volume sliders.
 * @module player
 */

import { state } from './state.js';
import {
  fetchSnapcastStatus, snapcastControl,
  setAudioVolume, fetchMaVolume, setMaVolume, fetchMaQueue,
  setSnapcastClientVolume, maFavorite,
  fetchAirplayStatus,
} from './api.js';

/** Format seconds as m:ss. */
export function fmtTime(s) {
  s = Math.max(0, Math.round(s));
  const m = Math.floor(s / 60);
  return m + ':' + String(s % 60).padStart(2, '0');
}

/** Update the progress bar by interpolating elapsed time. */
export function updateProgress() {
  if (state.npDuration <= 0 || state.npElapsed == null) return;
  const clientNow = Date.now() / 1000;
  const elapsed = state.npElapsedAt
    ? state.npElapsed + (clientNow - state.npElapsedAt)
    : state.npElapsed;
  const pos = Math.min(Math.max(0, elapsed), state.npDuration);
  document.getElementById('np-pos').textContent = fmtTime(pos);
  document.getElementById('np-dur').textContent = fmtTime(state.npDuration);
  document.getElementById('progress-fill').style.width = (pos / state.npDuration * 100) + '%';
}

/** Update the blurred album art background. */
function updatePlayerBackground(imageUrl) {
  const el = document.getElementById('player-bg');
  el.style.backgroundImage =
    `url('/api/ma/imageproxy?url=${encodeURIComponent(imageUrl)}')`;
}

/** Send a Snapcast playback control command. */
export async function snapControl(action) {
  if (!state.currentStreamId) return;
  // Optimistic UI update for play/pause
  if (action === 'play' || action === 'pause') {
    state.isPlaying = action === 'play';
    state.playStateLockUntil = Date.now() + 5000;
    const btn = document.getElementById('btn-playpause');
    btn.innerHTML = state.isPlaying
      ? '<span class="material-symbols-outlined">pause</span>'
      : '<span class="material-symbols-outlined">play_arrow</span>';
  }
  await snapcastControl(action, state.currentStreamId);
  setTimeout(pollSnapcast, 500);
}

/** Toggle play/pause. */
export function togglePlayPause() {
  snapControl(state.isPlaying ? 'pause' : 'play');
}

/** Handle Snapcast status data (from SSE or poll). */
export function handleSnapcastStatus(d) {
  if (d.error) {
    document.getElementById('snapcast-info').textContent = d.error;
    return;
  }

  const np = d.now_playing;
  if (np && !state.airplayActive) {
    document.getElementById('np-title').textContent = np.title || '—';
    const artist = Array.isArray(np.artist) ? np.artist.join(', ') : (np.artist || '').split(',').map(s => s.trim()).join(', ');
    document.getElementById('np-artist').textContent = artist;
    document.getElementById('np-album').textContent = np.album || '';
    const art = document.getElementById('np-art');
    if (np.artUrl) {
      const proxiedUrl = '/api/ma/imageproxy?url=' + encodeURIComponent(np.artUrl);
      art.src = proxiedUrl;
      art.style.display = '';
      if (np.artUrl !== state.lastImageUrl) {
        state.lastImageUrl = np.artUrl;
        updatePlayerBackground(np.artUrl);
      }
    } else {
      art.style.display = 'none';
    }
  } else if (!np && !state.airplayActive) {
    document.getElementById('np-title').textContent = 'Nothing playing';
    document.getElementById('np-artist').textContent = '';
    document.getElementById('np-album').textContent = '';
    document.getElementById('np-art').style.display = 'none';
    state.npDuration = 0;
    state.npElapsed = 0;
    state.npElapsedAt = 0;
    document.getElementById('np-pos').textContent = '0:00';
    document.getElementById('np-dur').textContent = '0:00';
    document.getElementById('progress-fill').style.width = '0%';
  }

  const c = d.controls || {};
  if (c.streamId) state.currentStreamId = c.streamId;
  if (!state.currentStreamId) {
    const maStream = d.streams.find(s => s.metadata);
    if (maStream) state.currentStreamId = maStream.id;
  }
  // Only update play state from SSE if no user action is pending
  if (Date.now() >= state.playStateLockUntil) {
    state.isPlaying = d.streams.some(s => s.status === 'playing');
    const btn = document.getElementById('btn-playpause');
    btn.innerHTML = state.isPlaying
      ? '<span class="material-symbols-outlined">pause</span>'
      : '<span class="material-symbols-outlined">play_arrow</span>';
  }
  const btn = document.getElementById('btn-playpause');
  btn.disabled = !state.currentStreamId;
  document.getElementById('btn-prev').disabled = !c.canGoPrevious && !state.currentStreamId;
  document.getElementById('btn-next').disabled = !c.canGoNext && !state.currentStreamId;

  let html = d.streams.filter(s => s.metadata).map(s =>
    `<span class="badge ${s.status === 'playing' ? 'badge-green' : 'badge-orange'}">${s.status}</span> `
  ).join('');
  if (d.clients.length === 0) {
    html += '<div style="color:var(--dim);margin-top:4px">No clients connected</div>';
  } else {
    html += d.clients.map(cl =>
      `<div>${cl.connected ? '🟢' : '🔴'} ${cl.name} ${cl.volume}%${cl.muted ? ' 🔇' : ''}</div>`
    ).join('');
    // Capture first connected client for volume/latency control
    const myClient = d.clients.find(cl => cl.connected);
    if (myClient) {
      state.snapClientId = myClient.id || '';
      const slider = document.getElementById('snap-vol-slider');
      if (slider && !slider.matches(':active')) {
        slider.value = myClient.volume;
        document.getElementById('snap-vol-val').textContent = myClient.volume + '%';
      }
    }
  }
  document.getElementById('snapcast-info').innerHTML = html;
}

/** Poll Snapcast status (fallback, used after control actions). */
export async function pollSnapcast() {
  try {
    handleSnapcastStatus(await fetchSnapcastStatus());
  } catch (e) {
    // Ignore
  }
}

/** Handle audio status data (from SSE or poll). */
export function handleAudioStatus(d) {
  const def = d.sinks.find(s => s.default);
  if (def && def.volume !== null) {
    const slider = document.getElementById('vol-slider');
    if (!slider.matches(':active')) {
      slider.value = Math.round(def.volume * 100);
      document.getElementById('vol-val').textContent = Math.round(def.volume * 100) + '%';
    }
  }
}

/** Handle Bluetooth status data (from SSE or poll). */
export function handleBtStatus(d) {
  document.getElementById('bt-status').innerHTML = d.connected
    ? `<span class="badge badge-green">${d.name || 'Connected'}</span>`
    : '<span class="badge badge-red">Off</span>';
  document.getElementById('bt-codec').textContent = d.codec
    ? d.codec.replace(/_/g, '-').toUpperCase() : '';
}

/** Poll MA player volume. */
export async function pollMaVolume() {
  try {
    const d = await fetchMaVolume();
    if (d.player_id) {
      state.maPlayerId = d.player_id;
      const slider = document.getElementById('ma-vol-slider');
      if (!slider.matches(':active')) {
        slider.value = d.volume || 0;
        document.getElementById('ma-vol-val').textContent = (d.volume || 0) + '%';
      }
    }
  } catch (e) {
    // Ignore
  }
}

/** Poll MA queue for track position, metadata, quality, lyrics. */
export async function pollMaQueue() {
  try {
    const d = await fetchMaQueue();
    if (d.queue_id) state.currentQueueId = d.queue_id;
    // If AirPlay is active, don't touch the player UI — pollAirplay owns it
    if (state.airplayActive) return;
    if (d.duration > 0) {
      state.npElapsed = d.elapsed_time || 0;
      state.npElapsedAt = d.server_time || (Date.now() / 1000);
      state.npDuration = d.duration || 0;
      updateProgress();

      if (d.uri) state.currentTrackUri = d.uri;

      // Audio Quality Badge
      const qEl = document.getElementById('np-quality');
      if (d.quality) {
        const qMap = { LQ: 'badge-orange', HQ: 'badge-green', HR: 'badge-cyan' };
        qEl.className = 'badge ' + (qMap[d.quality] || '');
        qEl.textContent = d.quality;
        qEl.style.display = '';
      } else { qEl.style.display = 'none'; }

      // Codec info
      const cEl = document.getElementById('np-codec');
      if (d.codec) {
        cEl.textContent = d.codec.toUpperCase() + ' ' + (d.sample_rate / 1000) + 'kHz/' + d.bit_depth + 'bit';
      } else { cEl.textContent = ''; }

      // Queue position
      const qpEl = document.getElementById('np-queue-pos');
      if (d.queue_total > 0) {
        qpEl.textContent = (d.queue_index + 1) + '/' + d.queue_total;
      } else { qpEl.textContent = ''; }

      // Shuffle
      const shEl = document.getElementById('np-shuffle');
      shEl.style.display = '';
      shEl.style.opacity = d.shuffle ? '1' : '0.3';
      state.currentShuffle = d.shuffle;

      // Repeat
      const rpEl = document.getElementById('np-repeat');
      rpEl.style.display = '';
      state.currentRepeat = d.repeat || 'off';
      if (state.currentRepeat === 'one') { rpEl.innerHTML = '<span class="material-symbols-outlined">repeat_one</span>'; rpEl.style.opacity = '1'; }
      else if (state.currentRepeat === 'all') { rpEl.innerHTML = '<span class="material-symbols-outlined">repeat</span>'; rpEl.style.opacity = '1'; }
      else { rpEl.innerHTML = '<span class="material-symbols-outlined">repeat</span>'; rpEl.style.opacity = '0.3'; }

      // Loudness target
      const lEl = document.getElementById('np-loudness');
      lEl.textContent = d.target_loudness != null ? d.target_loudness + ' LUFS' : '';

      // Popularity
      const pEl = document.getElementById('np-popularity');
      if (d.popularity != null && d.popularity > 0) {
        pEl.textContent = '🔥 ' + d.popularity + '%';
      } else { pEl.textContent = ''; }

      // Up Next
      const nxEl = document.getElementById('np-next');
      const nxName = document.getElementById('np-next-name');
      if (d.next_track) {
        nxName.textContent = d.next_track;
        nxEl.style.display = '';
      } else { nxEl.style.display = 'none'; }

      // Lyrics
      const lyCard = document.getElementById('lyrics-card');
      const lyText = document.getElementById('lyrics-text');
      const lyrics = d.lyrics || '';
      if (lyrics) {
        lyText.textContent = lyrics.replace(/\[\d+:\d+[\.\:]\d+\]/g, '').trim();
        lyCard.style.display = '';
      } else { lyCard.style.display = 'none'; }

      // Album art background — fallback to MA image if Snapcast didn't provide one
      if (d.image_url && d.image_url !== state.lastImageUrl && !state.lastImageUrl) {
        state.lastImageUrl = d.image_url;
        updatePlayerBackground(d.image_url);
      }

      // Show queue card and auto-expand on first load
      document.getElementById('queue-card').style.display = '';
      document.getElementById('queue-count').textContent = '(' + d.queue_total + ')';
      if (!state.queueVisible) {
        state.queueVisible = true;
        const list = document.getElementById('queue-list');
        const btn = document.getElementById('btn-queue-toggle');
        list.style.display = '';
        btn.textContent = 'Hide';
        import('./queue.js').then(m => m.loadQueue());
      }    }
  } catch (e) {
    // Ignore poll errors
  }
}

/** Initialize volume slider event listeners. */
export function initVolumeSliders() {
  document.getElementById('vol-slider').addEventListener('input', async function () {
    const vol = this.value / 100;
    document.getElementById('vol-val').textContent = this.value + '%';
    await setAudioVolume(vol);
  });

  document.getElementById('ma-vol-slider').addEventListener('input', async function () {
    const vol = parseInt(this.value, 10);
    document.getElementById('ma-vol-val').textContent = vol + '%';
    if (!state.maPlayerId) return;
    await setMaVolume(state.maPlayerId, vol);
  });

  let snapVolTimer = null;
  document.getElementById('snap-vol-slider').addEventListener('input', function () {
    const vol = parseInt(this.value, 10);
    document.getElementById('snap-vol-val').textContent = vol + '%';
    clearTimeout(snapVolTimer);
    snapVolTimer = setTimeout(async () => {
      if (!state.snapClientId) return;
      await setSnapcastClientVolume(state.snapClientId, vol);
    }, 150);
  });
}

/** Toggle favorite for current track. */
export async function toggleFavorite() {
  if (!state.currentTrackUri) return;
  const btn = document.getElementById('btn-favorite');
  btn.classList.toggle('active');
  await maFavorite(state.currentTrackUri);
}

/** Start a sleep timer. */
export function startSleepTimer(minutes) {
  cancelSleepTimer();
  if (!minutes || minutes <= 0) return;
  state.sleepTimerEnd = Date.now() + minutes * 60000;
  state.sleepTimerId = setTimeout(() => {
    snapControl('pause');
    state.sleepTimerId = null;
    state.sleepTimerEnd = 0;
    updateSleepTimerDisplay();
  }, minutes * 60000);
  updateSleepTimerDisplay();
}

/** Cancel the sleep timer. */
export function cancelSleepTimer() {
  if (state.sleepTimerId) {
    clearTimeout(state.sleepTimerId);
    state.sleepTimerId = null;
  }
  state.sleepTimerEnd = 0;
  updateSleepTimerDisplay();
}

/** Update sleep timer display. */
export function updateSleepTimerDisplay() {
  const el = document.getElementById('sleep-timer-status');
  if (!el) return;
  if (state.sleepTimerEnd > 0) {
    const remaining = Math.max(0, Math.ceil((state.sleepTimerEnd - Date.now()) / 60000));
    el.textContent = remaining + ' min';
    el.style.display = '';
  } else {
    el.style.display = 'none';
  }
}

/** Initialize seek bar (click + drag). */
export function initSeekBar() {
  const bar = document.getElementById('progress-bar');

  function seekTo(e) {
    if (state.npDuration <= 0 || !state.currentStreamId) return;
    const rect = bar.getBoundingClientRect();
    const x = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
    const pct = Math.max(0, Math.min(1, x / rect.width));
    const pos = pct * state.npDuration;
    document.getElementById('progress-fill').style.width = (pct * 100) + '%';
    document.getElementById('np-pos').textContent = fmtTime(pos);
    snapcastControl('seek', state.currentStreamId, { position: pos })
      .then(() => setTimeout(pollMaQueue, 500));
  }

  bar.addEventListener('click', seekTo);
  let dragging = false;
  bar.addEventListener('touchstart', function (e) { dragging = true; seekTo(e); }, { passive: true });
  bar.addEventListener('touchmove', function (e) { if (dragging) seekTo(e); }, { passive: true });
  bar.addEventListener('touchend', function () { dragging = false; });
}

/** Initialize swipe gestures on the player card. */
export function initSwipeGestures() {
  const card = document.getElementById('player-card');
  let startX = 0, startY = 0, startTime = 0;
  const MIN_SWIPE = 60;
  const MAX_TIME = 400;

  card.addEventListener('touchstart', function (e) {
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
    startTime = Date.now();
  }, { passive: true });

  card.addEventListener('touchend', function (e) {
    const dx = e.changedTouches[0].clientX - startX;
    const dy = e.changedTouches[0].clientY - startY;
    const dt = Date.now() - startTime;
    if (dt > MAX_TIME) return;
    if (Math.abs(dx) < MIN_SWIPE && Math.abs(dy) < MIN_SWIPE) return;
    if (Math.abs(dy) > Math.abs(dx)) return;
    if (dx > MIN_SWIPE) snapControl('previous');
    else if (dx < -MIN_SWIPE) snapControl('next');
  }, { passive: true });
}


/** Poll AirPlay status and update the now-playing display if active. */
export async function pollAirplay() {
  try {
    const d = await fetchAirplayStatus();
    const card = document.getElementById('player-card');
    state.airplayActive = !!d.active;
    if (d.active) {
      // Override Now Playing with AirPlay info
      document.getElementById('np-title').textContent = d.title || 'AirPlay';
      document.getElementById('np-artist').textContent = d.artist || '';
      document.getElementById('np-album').textContent = d.album || '';
      const art = document.getElementById('np-art');
      if (d.has_cover) {
        // Only reload cover if the track changed
        const key = d.title + '|' + d.artist;
        if (key !== state.airplayTrackKey) {
          state.airplayTrackKey = key;
          art.src = '/api/airplay/cover?t=' + encodeURIComponent(key);
        }
        art.style.display = '';
      }
      // AirPlay badge indicator
      const badge = document.getElementById('airplay-badge');
      if (badge) badge.style.display = '';
      card.classList.add('airplay-active');
      // Hide things that don't apply to AirPlay
      document.getElementById('btn-prev').style.visibility = 'hidden';
      document.getElementById('btn-next').style.visibility = 'hidden';
      document.getElementById('btn-playpause').style.visibility = 'hidden';
    } else {
      state.airplayTrackKey = '';
      const badge = document.getElementById('airplay-badge');
      if (badge) badge.style.display = 'none';
      card.classList.remove('airplay-active');
      document.getElementById('btn-prev').style.visibility = '';
      document.getElementById('btn-next').style.visibility = '';
      document.getElementById('btn-playpause').style.visibility = '';
    }
  } catch (e) {
    // Ignore
  }
}
