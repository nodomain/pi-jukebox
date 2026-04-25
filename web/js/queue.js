/**
 * Queue browser: load, toggle, actions (play, delete, move, clear, shuffle, repeat).
 * @module queue
 */

import { state } from './state.js';
import { fetchMaQueueItems, maQueueAction, maPlayMedia, maSaveQueueAsPlaylist } from './api.js';
import { fmtTime, showToast } from './player.js';

/**
 * Optimistically add a track to the queue UI and fire the API call.
 * The item appears instantly; a background reload syncs the real state.
 *
 * @param {string} uri - Track URI
 * @param {string} name - Display name
 * @param {string} artist - Artist name
 * @param {number} duration - Duration in seconds
 * @param {string} option - 'add', 'next', or 'play'
 */
export function addToQueueOptimistic(uri, name, artist, duration, option) {
  if (!state.currentQueueId || !uri) return;

  // 1. Inject into DOM immediately if queue is visible
  const list = document.getElementById('queue-list');
  const countEl = document.getElementById('queue-count');
  if (list && state.queueVisible) {
    const currentCount = list.querySelectorAll('.q-item').length;
    const idx = option === 'next' ? '→' : String(currentCount + 1);
    const displayName = artist ? `${artist} - ${name}` : name;
    const html = `<div class="q-item q-optimistic" style="animation:fadeIn .3s; opacity:0.7">
      <span class="q-play"><span class="material-symbols-outlined">play_arrow</span></span>
      <span class="q-idx">${idx}</span>
      <span class="q-name">${displayName}</span>
      <span class="q-dur">${fmtTime(duration)}</span>
      <span class="q-actions"></span>
    </div>`;
    if (option === 'next') {
      const current = list.querySelector('.q-current');
      if (current && current.nextElementSibling) {
        current.nextElementSibling.insertAdjacentHTML('beforebegin', html);
      } else {
        list.insertAdjacentHTML('beforeend', html);
      }
    } else {
      list.insertAdjacentHTML('beforeend', html);
    }
    // Update count badge
    if (countEl) {
      const m = countEl.textContent.match(/\d+/);
      if (m) countEl.textContent = `(${parseInt(m[0], 10) + 1})`;
    }
  }

  // 2. Fire API call in background
  maPlayMedia(uri, state.currentQueueId, option);

  // 3. Sync real state after a delay
  if (state.queueVisible) {
    setTimeout(loadQueue, 2000);
  }
}

/** Load and render queue items. */
export async function loadQueue() {
  if (!state.currentQueueId) return;
  const list = document.getElementById('queue-list');
  try {
    const d = await fetchMaQueueItems(state.currentQueueId);
    if (!d.items || d.items.length === 0) {
      list.innerHTML = '<div style="color:var(--dim);padding:8px">Empty</div>';
      return;
    }
    const curItemId = state.currentQueueItemId || '';
    list.innerHTML = d.items.map((item, i) => {
      const isCurrent = item.queue_item_id === curItemId;
      const dur = fmtTime(item.duration);
      return `<div class="q-item${isCurrent ? ' q-current' : ''}" data-action="play" data-id="${item.queue_item_id}" data-name="${item.name.replace(/"/g, '&quot;')}">
        <span class="q-play"><span class="material-symbols-outlined">${isCurrent ? 'equalizer' : 'play_arrow'}</span></span>
        <span class="q-idx">${i + 1}</span>
        <span class="q-name">${item.name}</span>
        <span class="q-dur">${dur}</span>
        <span class="q-actions">
          <button data-action="move-up" data-id="${item.queue_item_id}" title="Up">↑</button>
          <button data-action="move-down" data-id="${item.queue_item_id}" title="Down">↓</button>
          <button data-action="delete" data-id="${item.queue_item_id}" title="Remove">✕</button>
        </span>
      </div>`;
    }).join('');
    // Auto-scroll to current track within the queue container
    const current = list.querySelector('.q-current');
    if (current) {
      setTimeout(() => {
        list.scrollTop = current.offsetTop - list.offsetTop - list.clientHeight / 3;
      }, 100);
    }
  } catch (e) {
    list.innerHTML = '<div style="color:var(--dim)">Error loading queue</div>';
  }
}

/** Toggle queue list visibility. */
export function toggleQueue() {
  const list = document.getElementById('queue-list');
  const btn = document.getElementById('btn-queue-toggle');
  state.queueVisible = !state.queueVisible;
  if (state.queueVisible) {
    loadQueue();
    list.style.display = '';
    btn.textContent = 'Hide';
  } else {
    list.style.display = 'none';
    btn.textContent = 'Show';
  }
}

/** Perform a queue action and optionally reload the list. */
async function queueAction(action, extra = {}) {
  if (!state.currentQueueId) return;
  await maQueueAction({ action, queue_id: state.currentQueueId, ...extra });
  if (state.queueVisible) setTimeout(loadQueue, 500);
}

/** Play a specific queue item by ID, with immediate visual feedback. */
export function queuePlay(id, name) {
  // Immediately highlight the clicked item
  const list = document.getElementById('queue-list');
  list.querySelectorAll('.q-item').forEach(el => {
    const isSel = el.dataset.id === id;
    el.classList.toggle('q-current', isSel);
    const icon = el.querySelector('.q-play .material-symbols-outlined');
    if (icon) icon.textContent = isSel ? 'equalizer' : 'play_arrow';
  });
  // Update Now Playing title immediately
  if (name) {
    document.getElementById('np-title').textContent = name;
    document.getElementById('np-pos').textContent = '0:00';
    document.getElementById('progress-fill').style.width = '0%';
    // Reset lyrics so they reload for the new track
    state._lastLyricsKey = '';
    state._lrcLines = null;
    state._lastLrcIdx = -1;
    const lyCard = document.getElementById('lyrics-card');
    const lyText = document.getElementById('lyrics-text');
    if (lyCard && lyText) {
      lyText.innerHTML = '<span style="color:var(--dim)">Loading lyrics...</span>';
      lyCard.style.display = '';
    }
  }
  // Lock play state so SSE doesn't revert the queue highlight before the track starts
  state.playStateLockUntil = Date.now() + 5000;
  queueAction('play_index', { queue_item_id: id });
}

/** Delete a queue item by ID. */
export function queueDelete(id) { queueAction('delete', { queue_item_id: id }); }

/** Move a queue item up or down. */
export function queueMove(id, shift) { queueAction('move', { queue_item_id: id, pos_shift: shift }); }

/** Clear the entire queue (with confirmation). */
export function clearQueue() {
  if (confirm('Clear entire queue?')) queueAction('clear');
}

/** Toggle shuffle mode. */
export function toggleShuffle() {
  state.currentShuffle = !state.currentShuffle;
  const el = document.getElementById('np-shuffle');
  el.style.opacity = state.currentShuffle ? '1' : '0.3';
  queueAction('shuffle', { enabled: state.currentShuffle });
}

/** Cycle repeat mode: off → all → one → off. */
export function toggleRepeat() {
  const modes = ['off', 'all', 'one'];
  const next = modes[(modes.indexOf(state.currentRepeat) + 1) % modes.length];
  state.currentRepeat = next;
  const el = document.getElementById('np-repeat');
  if (next === 'one') {
    el.innerHTML = '<span class="material-symbols-outlined">repeat_one</span>';
    el.style.opacity = '1';
  } else if (next === 'all') {
    el.innerHTML = '<span class="material-symbols-outlined">repeat</span>';
    el.style.opacity = '1';
  } else {
    el.innerHTML = '<span class="material-symbols-outlined">repeat</span>';
    el.style.opacity = '0.3';
  }
  queueAction('repeat', { mode: next });
}

/** Initialize queue event delegation for click handlers. */
export function initQueueEvents() {
  const list = document.getElementById('queue-list');
  list.addEventListener('click', function (e) {
    const btn = e.target.closest('[data-action]');
    if (btn) {
      const action = btn.dataset.action;
      const id = btn.dataset.id;
      e.stopPropagation();
      if (action === 'play') {
        const row = btn.closest('.q-item');
        queuePlay(id, row?.dataset.name);
      }
      else if (action === 'move-up') queueMove(id, -1);
      else if (action === 'move-down') queueMove(id, 1);
      else if (action === 'delete') queueDelete(id);
      return;
    }
    // Tap on queue item toggles action buttons (mobile)
    const item = e.target.closest('.q-item');
    if (item) {
      list.querySelectorAll('.q-item.q-expanded').forEach(el => {
        if (el !== item) el.classList.remove('q-expanded');
      });
      item.classList.toggle('q-expanded');
    }
  });

  // Initialize touch drag reorder
  initQueueDrag();
}

/** Save current queue as a playlist. */
export async function saveQueueAsPlaylist() {
  if (!state.currentQueueId) {
    showToast('No active queue');
    return;
  }
  const name = prompt('Playlist name:');
  if (!name || !name.trim()) return;
  try {
    await maSaveQueueAsPlaylist(name.trim(), state.currentQueueId);
    showToast('Saved as "' + name.trim() + '"');
  } catch (e) {
    showToast('Failed to save playlist');
  }
}

/** Initialize touch-based drag reorder on queue items. */
function initQueueDrag() {
  const list = document.getElementById('queue-list');
  let dragItem = null;
  let dragId = '';
  let startY = 0;
  let startIndex = 0;
  let longPressTimer = null;
  let isDragging = false;
  let placeholder = null;

  function getItemIndex(el) {
    const items = Array.from(list.querySelectorAll('.q-item:not(.q-placeholder)'));
    return items.indexOf(el);
  }

  function getItemAtY(y) {
    const items = Array.from(list.querySelectorAll('.q-item:not(.q-placeholder):not(.q-dragging)'));
    for (const item of items) {
      const rect = item.getBoundingClientRect();
      if (y >= rect.top && y <= rect.bottom) return item;
    }
    return null;
  }

  list.addEventListener('touchstart', function (e) {
    const item = e.target.closest('.q-item');
    if (!item || e.target.closest('[data-action]') || e.target.closest('button')) return;
    startY = e.touches[0].clientY;
    const id = item.dataset.id;
    // Long press to start drag (500ms)
    longPressTimer = setTimeout(() => {
      isDragging = true;
      dragItem = item;
      dragId = id;
      startIndex = getItemIndex(item);
      item.classList.add('q-dragging');
      // Create placeholder
      placeholder = document.createElement('div');
      placeholder.className = 'q-item q-placeholder';
      placeholder.style.height = item.offsetHeight + 'px';
      item.parentNode.insertBefore(placeholder, item);
      // Position dragged item absolutely
      item.style.position = 'fixed';
      item.style.left = '0';
      item.style.right = '0';
      item.style.top = (e.touches[0].clientY - item.offsetHeight / 2) + 'px';
      item.style.zIndex = '1000';
      item.style.width = list.offsetWidth + 'px';
    }, 500);
  }, { passive: true });

  list.addEventListener('touchmove', function (e) {
    if (!isDragging || !dragItem) {
      // Cancel long press if finger moves too much before drag starts
      if (longPressTimer && Math.abs(e.touches[0].clientY - startY) > 10) {
        clearTimeout(longPressTimer);
        longPressTimer = null;
      }
      return;
    }
    e.preventDefault();
    const y = e.touches[0].clientY;
    dragItem.style.top = (y - dragItem.offsetHeight / 2) + 'px';
    // Move placeholder to indicate drop position
    const target = getItemAtY(y);
    if (target && target !== placeholder) {
      const targetRect = target.getBoundingClientRect();
      const mid = targetRect.top + targetRect.height / 2;
      if (y < mid) {
        list.insertBefore(placeholder, target);
      } else {
        list.insertBefore(placeholder, target.nextSibling);
      }
    }
  }, { passive: false });

  list.addEventListener('touchend', function () {
    clearTimeout(longPressTimer);
    longPressTimer = null;
    if (!isDragging || !dragItem) return;
    // Calculate position shift
    const endIndex = getItemIndex(placeholder);
    const shift = endIndex - startIndex;
    // Clean up drag state
    dragItem.classList.remove('q-dragging');
    dragItem.style.position = '';
    dragItem.style.left = '';
    dragItem.style.right = '';
    dragItem.style.top = '';
    dragItem.style.zIndex = '';
    dragItem.style.width = '';
    if (placeholder && placeholder.parentNode) {
      placeholder.parentNode.insertBefore(dragItem, placeholder);
      placeholder.remove();
    }
    placeholder = null;
    isDragging = false;
    // Fire API call if position changed
    if (shift !== 0 && dragId) {
      queueMove(dragId, shift);
    }
    dragItem = null;
    dragId = '';
  }, { passive: true });

  list.addEventListener('touchcancel', function () {
    clearTimeout(longPressTimer);
    longPressTimer = null;
    if (dragItem) {
      dragItem.classList.remove('q-dragging');
      dragItem.style.position = '';
      dragItem.style.left = '';
      dragItem.style.right = '';
      dragItem.style.top = '';
      dragItem.style.zIndex = '';
      dragItem.style.width = '';
    }
    if (placeholder && placeholder.parentNode) placeholder.remove();
    placeholder = null;
    isDragging = false;
    dragItem = null;
    dragId = '';
  }, { passive: true });
}
