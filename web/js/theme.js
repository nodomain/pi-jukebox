/**
 * Dark/light theme toggle.
 * Preference is stored in localStorage.
 * @module theme
 */

/** Initialize theme from localStorage on page load. */
export function initTheme() {
  const saved = localStorage.getItem('theme');
  if (saved === 'light') {
    document.documentElement.classList.add('light');
    document.getElementById('theme-toggle').textContent = '☀️';
  }
}

/** Toggle between dark and light theme. */
export function toggleTheme() {
  const root = document.documentElement;
  const btn = document.getElementById('theme-toggle');
  root.classList.toggle('light');
  const isLight = root.classList.contains('light');
  btn.textContent = isLight ? '☀️' : '🌙';
  localStorage.setItem('theme', isLight ? 'light' : 'dark');
}
