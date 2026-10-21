/* Runs before styles to apply the saved theme before the first paint. */
(() => {
  const root = document.documentElement;
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  const key = 'dawnpanel-theme';
  let preference = null;
  try { const saved = localStorage.getItem(key); if (saved === 'light' || saved === 'dark') preference = saved; } catch {}
  const initial = () => preference || (system.matches ? 'dark' : 'light');
  function syncSource(source) {
    const media = root.dataset.theme === 'light' ? 'all' : 'not all';
    if (source.media !== media) source.media = media;
  }
  function syncButton(button) {
    const light = root.dataset.theme === 'light';
    const label = light ? 'فعال‌کردن حالت شب' : 'فعال‌کردن حالت روز';
    button.setAttribute('aria-pressed', String(light));
    button.setAttribute('aria-label', label);
    button.title = label;
    const icon = button.querySelector('[data-theme-icon]');
    if (icon && icon.textContent !== (light ? '☾' : '☀')) icon.textContent = light ? '☾' : '☀';
  }
  function inspect(node) {
    if (!(node instanceof Element)) return;
    if (node.matches('source[data-theme-light]')) syncSource(node);
    if (node.matches('[data-theme-toggle]')) syncButton(node);
    node.querySelectorAll('source[data-theme-light]').forEach(syncSource);
    node.querySelectorAll('[data-theme-toggle]').forEach(syncButton);
  }
  function apply(theme) {
    root.dataset.theme = theme;
    const color = document.querySelector('meta[name="theme-color"]');
    if (color) color.content = theme === 'light' ? '#f5f6f8' : '#18191b';
    inspect(root);
    document.dispatchEvent(new CustomEvent('dawn:theme-change', { detail: { theme } }));
  }
  apply(initial());
  const observer = new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(inspect)));
  observer.observe(root, {childList: true, subtree: true});
  document.addEventListener('DOMContentLoaded', () => { inspect(root); observer.disconnect(); }, {once: true});
  document.addEventListener('click', event => {
    if (!(event.target instanceof Element) || !event.target.closest('[data-theme-toggle]')) return;
    preference = root.dataset.theme === 'light' ? 'dark' : 'light';
    try { localStorage.setItem(key, preference); } catch {}
    apply(preference);
  });
  system.addEventListener('change', () => { if (!preference) apply(initial()); });
  window.addEventListener('storage', event => {
    if (event.key !== key && event.key !== null) return;
    preference = event.newValue === 'dark' || event.newValue === 'light' ? event.newValue : null;
    apply(initial());
  });
})();
