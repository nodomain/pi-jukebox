/**
 * Dark/light theme toggle.
 * Preference is stored in localStorage.
 * @module theme
 */

/** Initialize theme from localStorage on page load. */
export function initTheme() {
  const saved = localStorage.getItem('theme');
  const btn = document.getElementById('theme-toggle');
  if (saved === 'light') {
    document.documentElement.classList.add('light');
    btn.innerHTML = '<span class="material-symbols-outlined">light_mode</span>';
  }
}

/** Toggle between dark and light theme. */
export function toggleTheme() {
  const root = document.documentElement;
  const btn = document.getElementById('theme-toggle');
  root.classList.toggle('light');
  const isLight = root.classList.contains('light');
  btn.innerHTML = isLight
    ? '<span class="material-symbols-outlined">light_mode</span>'
    : '<span class="material-symbols-outlined">dark_mode</span>';
  localStorage.setItem('theme', isLight ? 'light' : 'dark');
}
