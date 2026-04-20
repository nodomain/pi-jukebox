/**
 * FFT visualizer canvas driven by cava SSE stream.
 * Auto-adapts bar count from incoming data.
 * @module fft
 */

/** Initialize the FFT visualizer. */
export function initFFT() {
  const canvas = document.getElementById('fft-canvas');
  const ctx = canvas.getContext('2d');
  let bars = new Array(32).fill(0);
  let targetBars = new Array(32).fill(0);

  function resize() {
    canvas.width = canvas.offsetWidth * (window.devicePixelRatio || 1);
    canvas.height = canvas.offsetHeight * (window.devicePixelRatio || 1);
  }
  resize();
  window.addEventListener('resize', resize);

  function draw() {
    const w = canvas.width;
    const h = canvas.height;
    const n = bars.length;
    const gap = 2 * (window.devicePixelRatio || 1);
    const barW = (w - gap * (n + 1)) / n;

    ctx.clearRect(0, 0, w, h);

    for (let i = 0; i < n; i++) {
      bars[i] += (targetBars[i] - bars[i]) * 0.3;
      const val = bars[i] / 100;
      const barH = Math.max(1, val * h);
      const x = gap + i * (barW + gap);
      const y = h - barH;

      const hue = 210 + val * 60;
      const light = 45 + val * 20;
      ctx.fillStyle = `hsl(${hue}, 80%, ${light}%)`;
      ctx.beginPath();
      const r = Math.min(2, barW / 2);
      ctx.roundRect(x, y, barW, barH, [r, r, 0, 0]);
      ctx.fill();
    }
    requestAnimationFrame(draw);
  }
  draw();

  function connectFFT() {
    const es = new EventSource('/api/fft/stream');
    es.onmessage = function (e) {
      if (e.data === 'error') return;
      const vals = e.data.split(';').filter(Boolean).map(Number);
      if (vals.length > 0) {
        targetBars = vals;
        if (bars.length !== vals.length) bars = new Array(vals.length).fill(0);
      }
    };
    es.onerror = function () {
      es.close();
      setTimeout(connectFFT, 5000);
    };
  }
  connectFFT();
}
