/**
 * PipeWire EQ presets: load presets, apply selection.
 * @module equalizer
 */

import { fetchEqPresets, setEqPreset } from './api.js';
import { showToast } from './player.js';

/** Load and render EQ presets. */
async function loadEqPresets() {
  const container = document.getElementById('eq-presets');
  if (!container) return;
  try {
    const d = await fetchEqPresets();
    if (!d.presets || d.presets.length === 0) {
      container.innerHTML = '<div style="color:var(--dim)">No presets</div>';
      return;
    }
    container.innerHTML = d.presets.map(p => {
      const active = p.id === d.current;
      const bassLabel = p.bass > 0 ? '+' + p.bass : p.bass;
      const trebleLabel = p.treble > 0 ? '+' + p.treble : p.treble;
      const detail = p.id === 'flat' ? '' : ` <span style="font-size:0.7em; color:var(--dim)">(B:${bassLabel} T:${trebleLabel})</span>`;
      return `<button class="chip${active ? ' active' : ''}" data-eq="${p.id}">${p.label}${detail}</button>`;
    }).join('');
  } catch (e) {
    container.innerHTML = '<div style="color:var(--dim)">EQ unavailable</div>';
  }
}

/** Handle EQ preset selection. */
function handleEqClick(e) {
  const btn = e.target.closest('[data-eq]');
  if (!btn) return;
  const preset = btn.dataset.eq;
  // Optimistic UI
  const container = document.getElementById('eq-presets');
  container.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  setEqPreset(preset).then(d => {
    showToast('EQ: ' + (d.preset || preset));
  }).catch(() => {
    showToast('Failed to set EQ');
    loadEqPresets(); // Revert
  });
}

/** Initialize equalizer section. */
export function initEqualizer() {
  const container = document.getElementById('eq-presets');
  if (!container) return;
  container.addEventListener('click', handleEqClick);
  // Load presets when System details section is opened
  const details = document.getElementById('tech-details');
  if (details) {
    details.addEventListener('toggle', function () {
      if (details.open) loadEqPresets();
    });
    if (details.open) loadEqPresets();
  }
}
