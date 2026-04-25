/**
 * Multi-room player transfer: list MA players, transfer playback.
 * @module multiroom
 */

import { fetchMaPlayers, maTransferPlayback } from './api.js';
import { showToast } from './player.js';

/** Load and render the MA players list in the System section. */
async function loadPlayers() {
  const container = document.getElementById('multiroom-list');
  if (!container) return;
  try {
    const d = await fetchMaPlayers();
    if (!d.players || d.players.length === 0) {
      container.innerHTML = '<div style="color:var(--dim)">No players found</div>';
      return;
    }
    container.innerHTML = d.players.map(p => {
      const isJukebox = p.player_id === 'ma_jukebox' || p.name.toLowerCase().includes('jukebox');
      const statusBadge = p.available
        ? '<span class="badge badge-green">online</span>'
        : '<span class="badge badge-red">offline</span>';
      const transferBtn = !isJukebox && p.available
        ? `<button class="secondary" data-transfer="${p.player_id}" style="padding:4px 10px; font-size:0.75em">Transfer</button>`
        : '';
      const label = isJukebox ? p.name + ' (this)' : p.name;
      return `<div style="display:flex; align-items:center; justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--border)">
        <span>${statusBadge} ${label}</span>
        ${transferBtn}
      </div>`;
    }).join('');
  } catch (e) {
    container.innerHTML = '<div style="color:var(--dim)">Error loading players</div>';
  }
}

/** Handle transfer button clicks. */
function handleTransfer(e) {
  const btn = e.target.closest('[data-transfer]');
  if (!btn) return;
  const targetId = btn.dataset.transfer;
  btn.disabled = true;
  btn.textContent = '...';
  maTransferPlayback(targetId).then(() => {
    showToast('Playback transferred');
    btn.textContent = 'Done';
    setTimeout(() => loadPlayers(), 2000);
  }).catch(() => {
    showToast('Transfer failed');
    btn.disabled = false;
    btn.textContent = 'Transfer';
  });
}

/** Initialize multi-room section. */
export function initMultiRoom() {
  const container = document.getElementById('multiroom-list');
  if (!container) return;
  container.addEventListener('click', handleTransfer);
  // Load players when the System details section is opened
  const details = document.getElementById('tech-details');
  if (details) {
    details.addEventListener('toggle', function () {
      if (details.open) loadPlayers();
    });
    // Also load if already open
    if (details.open) loadPlayers();
  }
}
