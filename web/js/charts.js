/**
 * Chart.js setup and polling for system metrics.
 * @module charts
 */

/* global Chart */

import { fetchStats, fetchSnapcastJitter } from './api.js';

const MAX_POINTS = 100;
const labels = [];
let prevRx = 0;
let prevTx = 0;
let prevSdWrites = 0;
let firstPoll = true;

/** Create a dataset config object. */
function ds(label, color) {
  return { label, data: [], borderColor: color, backgroundColor: color + '20', fill: true };
}

/** Create a standard line chart. */
function makeChart(id, datasets, yOpts = {}) {
  return new Chart(document.getElementById(id), {
    type: 'line',
    data: { labels, datasets },
    options: {
      animation: false, responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#888', boxWidth: 10, font: { size: 10 } } },
        tooltip: {
          enabled: true, mode: 'index', intersect: false,
          callbacks: { label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(2) },
        },
      },
      scales: {
        x: { display: true, ticks: { color: '#555', font: { size: 8 }, maxTicksLimit: 5, maxRotation: 0 }, grid: { display: false } },
        y: { ...yOpts, ticks: { color: '#888', font: { size: 9 } }, grid: { color: '#2a2d37' } },
      },
      elements: { point: { radius: 0, hitRadius: 8, hoverRadius: 4 }, line: { tension: 0.3, borderWidth: 1.5 } },
    },
  });
}

/** Push values into chart datasets, trimming to MAX_POINTS. */
function pushData(chart, ...vals) {
  vals.forEach((v, i) => {
    chart.data.datasets[i].data.push(v);
    if (chart.data.datasets[i].data.length > MAX_POINTS) chart.data.datasets[i].data.shift();
  });
}

/** Format uptime seconds as "Xh Ym". */
function formatUptime(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? h + 'h ' + m + 'm' : m + 'm';
}

/** Render throttle flags into the DOM. */
function renderThrottle(t) {
  const el = document.getElementById('throttle-flags');
  if (!t || !t.raw) { el.textContent = '—'; return; }
  const flags = [
    ['UV', t.under_voltage], ['Freq⬇', t.freq_capped], ['Throt', t.throttled], ['TempLim', t.soft_temp_limit],
    ['UV*', t.under_voltage_occurred], ['Freq⬇*', t.freq_capped_occurred], ['Throt*', t.throttled_occurred], ['TempLim*', t.soft_temp_limit_occurred],
  ];
  const active = flags.filter(f => f[1]);
  if (active.length === 0) {
    el.innerHTML = '<span class="flag flag-ok">All OK</span>';
  } else {
    el.innerHTML = active.map(f => `<span class="flag flag-warn">${f[0]}</span>`).join('');
  }
}

// Chart instances (created on init)
let sysChart, cpuChart, wifiChart, loadChart, trafficChart, sdChart, jitterChart;

/** Initialize all chart instances. Must be called after DOM is ready. */
export function initCharts() {
  sysChart = makeChart('chart-system', [ds('Temp °C', '#ff9800'), ds('Mem %', '#4a9eff')], { min: 0, max: 100 });
  cpuChart = makeChart('chart-cpu', [ds('MHz', '#4caf50')], { min: 0 });
  wifiChart = makeChart('chart-wifi', [ds('dBm', '#4a9eff')]);
  loadChart = makeChart('chart-load', [ds('1m', '#4a9eff'), ds('5m', '#4caf50'), ds('15m', '#ff9800')], { min: 0 });
  trafficChart = makeChart('chart-traffic', [ds('RX', '#4caf50'), ds('TX', '#ff9800')], { min: 0 });
  sdChart = makeChart('chart-sd', [ds('Writes', '#f44336')], { min: 0 });

  jitterChart = new Chart(document.getElementById('chart-jitter'), {
    type: 'line',
    data: {
      datasets: [
        { label: 'pBuffer', data: [], borderColor: '#4a9eff', backgroundColor: '#4a9eff20', fill: false, pointRadius: 3, showLine: true, tension: 0.3 },
        { label: 'pShortBuffer', data: [], borderColor: '#ff9800', backgroundColor: '#ff980020', fill: false, pointRadius: 3, showLine: true, tension: 0.3 },
        { label: 'pMiniBuffer', data: [], borderColor: '#f44336', backgroundColor: '#f4433620', fill: false, pointRadius: 3, showLine: true, tension: 0.3 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      scales: {
        x: {
          type: 'linear', display: true,
          ticks: { color: '#555', font: { size: 8 }, maxTicksLimit: 6, maxRotation: 0, callback: v => new Date(v * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) },
          grid: { display: false },
        },
        y: { display: true, ticks: { color: '#555', font: { size: 8 } }, grid: { color: '#333' }, title: { display: true, text: 'ms', color: '#777', font: { size: 9 } } },
      },
      plugins: { legend: { labels: { color: '#aaa', font: { size: 9 } } } },
    },
  });
}

const POLL_MS = 3000;

/** Handle stats data (from SSE or poll) and update charts + DOM. */
export function handleStats(d) {
  const now = new Date().toLocaleTimeString();
  labels.push(now);
  if (labels.length > MAX_POINTS) labels.shift();

  document.getElementById('temp').textContent = d.temp.toFixed(1) + '°';
  document.getElementById('cpu-freq').textContent = Math.round(d.cpu_freq_mhz) + 'M';
  const memPct = d.mem_total_kb ? Math.round(d.mem_used_kb / d.mem_total_kb * 100) : 0;
  document.getElementById('mem').textContent = memPct + '%';
  document.getElementById('wifi-signal').textContent = d.wifi.signal || '—';
  document.getElementById('uptime').textContent = formatUptime(d.uptime);
  document.getElementById('load').textContent = (d.load || []).join(' ');
  document.getElementById('sd-writes').textContent = d.sd_writes;
  renderThrottle(d.throttle);

  const sigNum = parseFloat(d.wifi.signal) || -90;
  pushData(sysChart, d.temp, memPct); sysChart.update();
  pushData(cpuChart, d.cpu_freq_mhz); cpuChart.update();
  pushData(wifiChart, sigNum); wifiChart.update();
  const l = (d.load || []).map(parseFloat);
  if (l.length === 3) { pushData(loadChart, l[0], l[1], l[2]); loadChart.update(); }

  const rx = d.wifi.rx_bytes || 0;
  const tx = d.wifi.tx_bytes || 0;
  if (!firstPoll) {
    pushData(trafficChart, (rx - prevRx) / 1024 / (POLL_MS / 1000), (tx - prevTx) / 1024 / (POLL_MS / 1000));
    trafficChart.update();
    pushData(sdChart, d.sd_writes - prevSdWrites);
    sdChart.update();
  }
  prevRx = rx; prevTx = tx; prevSdWrites = d.sd_writes; firstPoll = false;
}

/** Poll system stats (fallback for initial load). */
export async function pollStats() {
  try {
    handleStats(await fetchStats());
  } catch (e) {
    console.error('poll error', e);
  }
}

const typeIdx = { pBuffer: 0, pShortBuffer: 1, pMiniBuffer: 2 };

/** Poll Snapcast buffer jitter and update the jitter chart. */
export async function pollJitter() {
  try {
    const d = await fetchSnapcastJitter();
    jitterChart.data.datasets.forEach(dataset => { dataset.data = []; });
    (d.points || []).forEach(p => {
      const i = typeIdx[p.type];
      if (i !== undefined) {
        jitterChart.data.datasets[i].data.push({ x: p.ts, y: Math.round(p.us / 1000 * 10) / 10 });
      }
    });
    jitterChart.update();
  } catch (e) {
    // Ignore
  }
}

export { POLL_MS };
