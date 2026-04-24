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
  const ATTACK = 0.25;   // gentle rise
  const DECAY = 0.94;    // slow, smooth fall

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
    const gap = 1 * dpr;
    const barW = Math.max(2, (w - gap * (n + 1)) / n);

    ctx.clearRect(0, 0, w, h);

    for (let i = 0; i < n; i++) {
      const target = (targetBars[i] || 0) / 100;
      const current = bars[i] || 0;
      // Smooth interpolation
      bars[i] = target > current
        ? current + (target - current) * ATTACK
        : current + (target - current) * (1 - DECAY);

      const val = Math.min(1, Math.max(0, bars[i]));
      if (val < 0.008) continue;

      const barH = val * h * 0.85;
      const x = gap + i * (barW + gap);
      const y = h - barH;

      // Soft gradient: muted blue → teal, low opacity
      const alpha = 0.3 + val * 0.5;
      const grad = ctx.createLinearGradient(x, h, x, y);
      grad.addColorStop(0, `hsla(210, 60%, 50%, ${alpha * 0.3})`);
      grad.addColorStop(0.6, `hsla(200, 55%, 58%, ${alpha * 0.7})`);
      grad.addColorStop(1, `hsla(190, 50%, ${60 + val * 20}%, ${alpha})`);

      ctx.fillStyle = grad;
      const r = Math.min(3 * dpr, barW / 2);
      ctx.beginPath();
      ctx.roundRect(x, y, barW, barH, [r, r, 0, 0]);
      ctx.fill();

      // Subtle glow on loud bars
      if (val > 0.6) {
        ctx.shadowColor = `hsla(200, 60%, 60%, ${(val - 0.6) * 0.4})`;
        ctx.shadowBlur = 8 * dpr;
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
