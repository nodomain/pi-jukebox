/**
 * FFT visualizer canvas driven by cava SSE stream.
 * Features: fast attack/slow decay, gradient bars, glow, reflection.
 * @module fft
 */

/** Initialize the FFT visualizer. */
export function initFFT() {
  const canvas = document.getElementById('fft-canvas');
  const ctx = canvas.getContext('2d');
  let bars = [];
  let targetBars = [];
  const ATTACK = 0.7;   // fast rise
  const DECAY = 0.88;   // slow fall

  function resize() {
    canvas.width = canvas.offsetWidth * (window.devicePixelRatio || 1);
    canvas.height = canvas.offsetHeight * (window.devicePixelRatio || 1);
  }
  resize();
  window.addEventListener('resize', resize);

  function draw() {
    const w = canvas.width;
    const h = canvas.height;
    const n = bars.length || 1;
    const dpr = window.devicePixelRatio || 1;
    const gap = 1.5 * dpr;
    const barW = Math.max(1, (w - gap * (n + 1)) / n);

    ctx.clearRect(0, 0, w, h);

    for (let i = 0; i < n; i++) {
      const target = (targetBars[i] || 0) / 100;
      const current = bars[i] || 0;
      // Fast attack, slow decay
      bars[i] = target > current
        ? current + (target - current) * ATTACK
        : current * DECAY;

      const val = Math.min(1, bars[i]);
      if (val < 0.005) continue;

      const barH = val * h * 0.85;
      const x = gap + i * (barW + gap);
      const y = h - barH;

      // Gradient: accent blue → cyan → white at peak
      const grad = ctx.createLinearGradient(x, h, x, y);
      grad.addColorStop(0, `hsla(210, 90%, 55%, 0.4)`);
      grad.addColorStop(0.5, `hsla(200, 85%, 60%, ${0.6 + val * 0.3})`);
      grad.addColorStop(1, `hsla(190, 80%, ${65 + val * 25}%, ${0.8 + val * 0.2})`);

      ctx.fillStyle = grad;
      const r = Math.min(2 * dpr, barW / 2);
      ctx.beginPath();
      ctx.roundRect(x, y, barW, barH, [r, r, 0, 0]);
      ctx.fill();

      // Subtle glow on loud bars
      if (val > 0.5) {
        ctx.shadowColor = `hsla(200, 90%, 65%, ${(val - 0.5) * 0.6})`;
        ctx.shadowBlur = 6 * dpr;
        ctx.fillRect(x, y, barW, 1);
        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;
      }
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
