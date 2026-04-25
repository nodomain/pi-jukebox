/**
 * Search, AI recommendations, recently played, and playlist browser.
 * @module browse
 */

import { state } from './state.js';
import { maSearch, fetchRecentlyPlayed, fetchPlaylists, maPlayMedia, fetchAlbumTracks, fetchPlaylistTracks } from './api.js';
import { fmtTime } from './player.js';
import { addToQueueOptimistic } from './queue.js';

let searchTimeout = null;
let recentVisible = false;
let playlistsVisible = false;
let searchFilter = 'track,album,playlist';
let aiMode = false;

/** Initialize search input with debounce. */
export function initSearch() {
  const input = document.getElementById('search-input');
  const container = document.getElementById('search-results');
  const addAllBtn = document.getElementById('btn-add-all');

  input.addEventListener('input', function () {
    clearTimeout(searchTimeout);
    const q = this.value.trim();
    if (!q) {
      container.style.display = 'none';
      addAllBtn.style.display = 'none';
      return;
    }
    if (aiMode) return; // AI mode uses Enter, not debounce
    searchTimeout = setTimeout(() => doSearch(q), 400);
  });

  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && aiMode) {
      e.preventDefault();
      const q = this.value.trim();
      if (q) doAiRecommend(q);
    }
  });

  // Filter chips
  document.getElementById('search-filters').addEventListener('click', function (e) {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    this.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');

    if (chip.dataset.filter === 'ai') {
      aiMode = true;
      input.placeholder = 'Describe what you want to hear... (Enter to search)';
      container.style.display = 'none';
      addAllBtn.style.display = 'none';
    } else {
      aiMode = false;
      searchFilter = chip.dataset.filter;
      input.placeholder = 'Search tracks, albums, playlists...';
      addAllBtn.style.display = 'none';
      const q = input.value.trim();
      if (q) doSearch(q);
    }
  });

  // Event delegation for search results
  container.addEventListener('click', function (e) {
    const btn = e.target.closest('[data-action]');
    if (btn) {
      const action = btn.dataset.action;
      const uri = btn.dataset.uri;
      if (!uri || !state.currentQueueId) return;
      e.stopPropagation();
      const name = btn.dataset.name || '';
      const artist = btn.dataset.artist || '';
      const dur = parseFloat(btn.dataset.dur) || 0;
      addToQueueOptimistic(uri, name, artist, dur, action);
      btn.style.opacity = '0.3';
      setTimeout(() => { btn.style.opacity = ''; }, 500);
      return;
    }
    const item = e.target.closest('.search-item.expandable');
    if (item) {
      e.stopPropagation();
      expandAlbum(item);
    }
  });
}

/** Add all visible results to queue (first with play, rest with add). */
export function addAllResults() {
  if (!state.currentQueueId) return;
  const btns = document.querySelectorAll('#search-results [data-action="add"]');
  let first = true;
  btns.forEach(btn => {
    const uri = btn.dataset.uri;
    if (uri) {
      const name = btn.dataset.name || '';
      const artist = btn.dataset.artist || '';
      const dur = parseFloat(btn.dataset.dur) || 0;
      addToQueueOptimistic(uri, name, artist, dur, first ? 'play' : 'add');
      btn.style.opacity = '0.3';
      first = false;
    }
  });
}

/** Perform library search and render results. */
async function doSearch(query) {
  const container = document.getElementById('search-results');
  const addAllBtn = document.getElementById('btn-add-all');
  addAllBtn.style.display = 'none';
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

/** Perform AI recommendation via SSE stream. */
async function doAiRecommend(prompt) {
  const container = document.getElementById('search-results');
  const addAllBtn = document.getElementById('btn-add-all');
  const statusEl = document.getElementById('search-status');

  // Get current track for context
  let artist = document.getElementById('np-artist').textContent.trim();
  let track = document.getElementById('np-title').textContent.trim();
  if (!artist || !track || track === '—' || track === 'Nothing playing') {
    try {
      const q = await fetch('/api/ma/queue').then(r => r.json());
      if (q.name) {
        const parts = q.name.split(' - ');
        if (parts.length >= 2) {
          artist = parts[0].trim();
          track = parts.slice(1).join(' - ').trim();
        } else { track = q.name; artist = ''; }
      }
    } catch { /* ignore */ }
  }

  container.style.display = '';
  container.innerHTML = '';
  statusEl.textContent = 'Connecting...';
  statusEl.style.display = '';
  addAllBtn.style.display = 'none';

  try {
    const resp = await fetch('/api/recommend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ artist: artist || 'Various', track: track || 'Unknown', mood: prompt }),
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split('\n\n');
      buffer = parts.pop();

      for (const part of parts) {
        let event = 'message';
        let data = '';
        for (const line of part.split('\n')) {
          if (line.startsWith('event: ')) event = line.slice(7);
          else if (line.startsWith('data: ')) data = line.slice(6);
        }
        if (!data) continue;
        try {
          const parsed = JSON.parse(data);
          if (event === 'status') {
            statusEl.textContent = parsed;
          } else if (event === 'track') {
            container.insertAdjacentHTML('beforeend', renderSearchItem({
              ...parsed, type: 'track',
            }));
          } else if (event === 'done') {
            const total = parsed.total || 0;
            statusEl.textContent = total > 0
              ? `✨ ${total} recommendation${total !== 1 ? 's' : ''}`
              : 'No recommendations found';
            if (total > 0) addAllBtn.style.display = '';
            setTimeout(() => { statusEl.style.display = 'none'; }, 4000);
          }
        } catch { /* skip */ }
      }
    }
  } catch (e) {
    statusEl.textContent = 'Recommendation failed';
  }
}

/** Map provider URI prefix to a display icon/emoji. */
function providerIcon(uri) {
  if (!uri) return '';
  const p = uri.split('://')[0].toLowerCase();
  if (p.startsWith('spotify')) return '<span class="s-provider" title="Spotify">🟢</span>';
  if (p.startsWith('apple_music')) return '<span class="s-provider" title="Apple Music">🍎</span>';
  if (p.startsWith('tidal')) return '<span class="s-provider" title="Tidal">🌊</span>';
  if (p.startsWith('ytmusic') || p.startsWith('youtube')) return '<span class="s-provider" title="YouTube Music">▶️</span>';
  if (p.startsWith('tunein') || p.startsWith('radio')) return '<span class="s-provider" title="Radio">📻</span>';
  if (p === 'library') return '<span class="s-provider" title="Library">📚</span>';
  return '';
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
  const pIcon = providerIcon(item.uri);

  return `<div class="search-item${isExpandable ? ' expandable' : ''}"${isExpandable ? ` data-expand-type="${item.type}" data-item-id="${itemId}" data-provider="${provider}"` : ''} style="animation:fadeIn .3s">
    ${thumb}
    <div class="s-info">
      <div class="s-name">${expandIcon}${item.name}</div>
      <div class="s-artist">${item.artist || ''} ${pIcon}${item.type !== 'track' ? `<span class="s-type">${item.type}</span>` : ''}</div>
    </div>
    ${dur ? `<span style="color:var(--dim);font-size:0.75em">${dur}</span>` : ''}
    <span class="s-actions">
      <button data-action="play" data-uri="${item.uri}" data-name="${(item.name || '').replace(/"/g, '&quot;')}" data-artist="${(item.artist || '').replace(/"/g, '&quot;')}" data-dur="${item.duration || 0}" title="Play now">▶</button>
      <button data-action="next" data-uri="${item.uri}" data-name="${(item.name || '').replace(/"/g, '&quot;')}" data-artist="${(item.artist || '').replace(/"/g, '&quot;')}" data-dur="${item.duration || 0}" title="Play next">⏭</button>
      <button data-action="add" data-uri="${item.uri}" data-name="${(item.name || '').replace(/"/g, '&quot;')}" data-artist="${(item.artist || '').replace(/"/g, '&quot;')}" data-dur="${item.duration || 0}" title="Add to queue">+</button>
    </span>
  </div>`;
}

/** Expand an album/playlist to show its tracks. */
async function expandAlbum(el) {
  const icon = el.querySelector('.s-expand');
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
          <button data-action="play" data-uri="${t.uri}" data-name="${(t.name || '').replace(/"/g, '&quot;')}" data-artist="${(t.artist || '').replace(/"/g, '&quot;')}" data-dur="${t.duration || 0}" title="Play">▶</button>
          <button data-action="next" data-uri="${t.uri}" data-name="${(t.name || '').replace(/"/g, '&quot;')}" data-artist="${(t.artist || '').replace(/"/g, '&quot;')}" data-dur="${t.duration || 0}" title="Next">⏭</button>
          <button data-action="add" data-uri="${t.uri}" data-name="${(t.name || '').replace(/"/g, '&quot;')}" data-artist="${(t.artist || '').replace(/"/g, '&quot;')}" data-dur="${t.duration || 0}" title="Add">+</button>
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

export function toggleRecent() {
  recentVisible = !recentVisible;
  document.getElementById('recent-list').style.display = recentVisible ? '' : 'none';
  document.getElementById('btn-recent-toggle').textContent = recentVisible ? 'Hide' : 'Show';
}

export function playRecent(el) {
  const uri = el.dataset.uri;
  if (!uri || !state.currentQueueId) return;
  maPlayMedia(uri, state.currentQueueId, 'play');
}

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
    list.innerHTML = '<div class="pl-grid">' + d.items.filter(i => i.name).map(item => {
      const img = item.image_url
        ? `<img class="pl-cover" src="/api/ma/imageproxy?url=${encodeURIComponent(item.image_url)}" alt="" loading="lazy">`
        : '<div class="pl-cover pl-cover-empty">🎵</div>';
      return `<div class="pl-tile" data-uri="${item.uri}" onclick="playPlaylist(this)">
        ${img}
        <div class="pl-label">${item.name}</div>
      </div>`;
    }).join('') + '</div>';
  } catch (e) {
    card.style.display = 'none';
  }
}

export function togglePlaylists() {
  playlistsVisible = !playlistsVisible;
  document.getElementById('playlists-list').style.display = playlistsVisible ? '' : 'none';
  document.getElementById('btn-playlists-toggle').textContent = playlistsVisible ? 'Hide' : 'Show';
}

export function playPlaylist(el) {
  const uri = el.dataset.uri;
  if (!uri || !state.currentQueueId) return;
  maPlayMedia(uri, state.currentQueueId, 'play');
}
