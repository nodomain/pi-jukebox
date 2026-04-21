/**
 * Search, recently played, and playlist browser.
 * @module browse
 */

import { state } from './state.js';
import { maSearch, fetchRecentlyPlayed, fetchPlaylists, maPlayMedia, fetchAlbumTracks, fetchPlaylistTracks } from './api.js';
import { fmtTime } from './player.js';

let searchTimeout = null;
let recentVisible = true;
let playlistsVisible = true;
let searchFilter = 'track,album,playlist';

/** Initialize search input with debounce. */
export function initSearch() {
  const input = document.getElementById('search-input');
  input.addEventListener('input', function () {
    clearTimeout(searchTimeout);
    const q = this.value.trim();
    if (!q) {
      document.getElementById('search-results').style.display = 'none';
      return;
    }
    searchTimeout = setTimeout(() => doSearch(q), 400);
  });

  // Filter chips
  document.getElementById('search-filters').addEventListener('click', function (e) {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    this.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    searchFilter = chip.dataset.filter;
    const q = input.value.trim();
    if (q) doSearch(q);
  });

  // Event delegation for search results
  document.getElementById('search-results').addEventListener('click', function (e) {
    // Handle play/next/add buttons
    const btn = e.target.closest('[data-action]');
    if (btn) {
      const action = btn.dataset.action;
      const uri = btn.dataset.uri;
      if (!uri || !state.currentQueueId) return;
      e.stopPropagation();
      maPlayMedia(uri, state.currentQueueId, action);
      btn.style.opacity = '0.3';
      setTimeout(() => { btn.style.opacity = ''; }, 500);
      return;
    }
    // Handle album/playlist expand
    const item = e.target.closest('.search-item.expandable');
    if (item) {
      e.stopPropagation();
      expandAlbum(item);
    }
  });
}

/** Perform search and render results. */
async function doSearch(query) {
  const container = document.getElementById('search-results');
  container.style.display = '';
  container.innerHTML = '<div style="color:var(--dim);padding:8px">Searching...</div>';
  try {
    const d = await maSearch(query, searchFilter);
    const types = searchFilter.split(',');
    const all = [
      ...(types.includes('track') ? (d.tracks || []).map(t => ({ ...t, type: 'track' })) : []),
      ...(types.includes('album') ? (d.albums || []).map(a => ({ ...a, type: 'album' })) : []),
      ...(types.includes('playlist') ? (d.playlists || []).map(p => ({ ...p, type: 'playlist' })) : []),
    ];
    if (all.length === 0) {
      container.innerHTML = '<div style="color:var(--dim);padding:8px">No results</div>';
      return;
    }
    container.innerHTML = all.map(item => renderSearchItem(item)).join('');
  } catch (e) {
    container.innerHTML = '<div style="color:var(--dim);padding:8px">Search failed</div>';
  }
}

/** Render a single search result item. */
function renderSearchItem(item) {
  const thumb = item.image_url
    ? `<img class="s-thumb" src="/api/ma/imageproxy?url=${encodeURIComponent(item.image_url)}" alt="">`
    : '<div class="s-thumb"></div>';
  const dur = item.duration ? fmtTime(item.duration) : '';
  const isExpandable = item.type === 'album' || item.type === 'playlist';
  const itemId = item.uri ? item.uri.split('/').pop() : '';
  const provider = item.uri ? item.uri.split('://')[0] : 'library';
  const expandIcon = isExpandable ? '<span class="s-expand material-symbols-outlined" style="font-size:18px;color:var(--dim)">expand_more</span>' : '';

  return `<div class="search-item${isExpandable ? ' expandable' : ''}"${isExpandable ? ` data-expand-type="${item.type}" data-item-id="${itemId}" data-provider="${provider}"` : ''}>
    ${thumb}
    <div class="s-info">
      <div class="s-name">${expandIcon}${item.name}</div>
      <div class="s-artist">${item.artist || ''} <span class="s-type">${item.type}</span></div>
    </div>
    ${dur ? `<span style="color:var(--dim);font-size:0.75em">${dur}</span>` : ''}
    <span class="s-actions">
      <button data-action="play" data-uri="${item.uri}" title="Play now">▶</button>
      <button data-action="next" data-uri="${item.uri}" title="Play next">⏭</button>
      <button data-action="add" data-uri="${item.uri}" title="Add to queue">+</button>
    </span>
  </div>`;
}

/** Expand an album/playlist to show its tracks. */
async function expandAlbum(el) {
  const icon = el.querySelector('.s-expand');
  // Toggle off if already expanded
  const existing = el.nextElementSibling;
  if (existing && existing.classList.contains('album-tracks')) {
    existing.remove();
    if (icon) icon.textContent = 'expand_more';
    return;
  }
  if (icon) icon.textContent = 'expand_less';
  const type = el.dataset.expandType;
  const itemId = el.dataset.itemId;
  const provider = el.dataset.provider;
  if (!itemId) return;

  const detail = document.createElement('div');
  detail.className = 'album-tracks';
  detail.innerHTML = '<div style="color:var(--dim);padding:4px 8px;font-size:0.8em">Loading...</div>';
  el.after(detail);

  try {
    let tracks = [];
    if (type === 'album') {
      const d = await fetchAlbumTracks(itemId, provider);
      tracks = d.items || [];
    } else if (type === 'playlist') {
      const d = await fetchPlaylistTracks(itemId, provider);
      tracks = d.items || [];
    }
    if (tracks.length === 0) {
      detail.innerHTML = '<div style="color:var(--dim);padding:4px 8px;font-size:0.8em">No tracks</div>';
      return;
    }
    detail.innerHTML = tracks.map((t, i) =>
      `<div class="album-track">
        <span class="at-num">${t.track_number || i + 1}</span>
        <span class="at-name">${t.name}</span>
        <span class="at-dur">${fmtTime(t.duration)}</span>
        <span class="s-actions">
          <button data-action="play" data-uri="${t.uri}" title="Play">▶</button>
          <button data-action="next" data-uri="${t.uri}" title="Next">⏭</button>
          <button data-action="add" data-uri="${t.uri}" title="Add">+</button>
        </span>
      </div>`
    ).join('');
  } catch (e) {
    detail.innerHTML = '<div style="color:var(--dim);padding:4px 8px;font-size:0.8em">Error loading tracks</div>';
  }
}

/** Load and show recently played items. */
export async function loadRecent() {
  const card = document.getElementById('recent-card');
  const list = document.getElementById('recent-list');
  try {
    const d = await fetchRecentlyPlayed(20);
    if (!d.items || d.items.length === 0) {
      card.style.display = 'none';
      return;
    }
    card.style.display = '';
    list.innerHTML = d.items.map(item =>
      `<div class="recent-item" data-uri="${item.uri}" onclick="playRecent(this)">
        <span style="color:var(--dim)">▶</span>
        <span class="r-name">${item.name} <span class="r-artist">— ${item.artist}</span></span>
        <span style="color:var(--dim);font-size:0.75em">${fmtTime(item.duration)}</span>
      </div>`
    ).join('');
  } catch (e) {
    card.style.display = 'none';
  }
}

/** Toggle recently played visibility. */
export function toggleRecent() {
  recentVisible = !recentVisible;
  document.getElementById('recent-list').style.display = recentVisible ? '' : 'none';
  document.getElementById('btn-recent-toggle').textContent = recentVisible ? 'Hide' : 'Show';
}

/** Play a recently played item. */
export function playRecent(el) {
  const uri = el.dataset.uri;
  if (!uri || !state.currentQueueId) return;
  maPlayMedia(uri, state.currentQueueId, 'play');
}

/** Load and show playlists. */
export async function loadPlaylists() {
  const card = document.getElementById('playlists-card');
  const list = document.getElementById('playlists-list');
  try {
    const d = await fetchPlaylists();
    if (!d.items || d.items.length === 0) {
      card.style.display = 'none';
      return;
    }
    card.style.display = '';
    list.innerHTML = d.items.map(item =>
      `<div class="playlist-item" data-uri="${item.uri}" onclick="playPlaylist(this)">
        <span style="color:var(--dim)">▶</span>
        <span class="pl-name">${item.name}</span>
        ${item.owner ? `<span style="color:var(--dim);font-size:0.75em">${item.owner}</span>` : ''}
      </div>`
    ).join('');
  } catch (e) {
    card.style.display = 'none';
  }
}

/** Toggle playlists visibility. */
export function togglePlaylists() {
  playlistsVisible = !playlistsVisible;
  document.getElementById('playlists-list').style.display = playlistsVisible ? '' : 'none';
  document.getElementById('btn-playlists-toggle').textContent = playlistsVisible ? 'Hide' : 'Show';
}

/** Play a playlist. */
export function playPlaylist(el) {
  const uri = el.dataset.uri;
  if (!uri || !state.currentQueueId) return;
  maPlayMedia(uri, state.currentQueueId, 'play');
}
