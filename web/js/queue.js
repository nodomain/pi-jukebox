/**
 * Queue browser: load, toggle, actions (play, delete, move, clear, shuffle, repeat).
 * @module queue
 */

import { state } from './main.js';
import { fetchMaQueueItems, maQueueAction } from './api.js';
import { fmtTime } from './player.js';

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
    const qpText = document.getElementById('np-queue-pos').textContent;
    const curIdx = qpText ? parseInt(qpText.split('/')[0], 10) - 1 : -1;
    list.innerHTML = d.items.map((item, i) => {
      const isCurrent = i === curIdx;
      const dur = fmtTime(item.duration);
      return `<div class="q-item${isCurrent ? ' q-current' : ''}" data-action="play" data-id="${item.queue_item_id}">
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

/** Play a specific queue item by ID. */
export function queuePlay(id) { queueAction('play_index', { queue_item_id: id }); }

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
  queueAction('shuffle', { enabled: !state.currentShuffle });
}

/** Cycle repeat mode: off → all → one → off. */
export function toggleRepeat() {
  const modes = ['off', 'all', 'one'];
  const next = modes[(modes.indexOf(state.currentRepeat) + 1) % modes.length];
  queueAction('repeat', { mode: next });
}

/** Initialize queue event delegation for click handlers. */
export function initQueueEvents() {
  const list = document.getElementById('queue-list');
  list.addEventListener('click', function (e) {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    const id = btn.dataset.id;
    e.stopPropagation();
    if (action === 'play') queuePlay(id);
    else if (action === 'move-up') queueMove(id, -1);
    else if (action === 'move-down') queueMove(id, 1);
    else if (action === 'delete') queueDelete(id);
  });
}
