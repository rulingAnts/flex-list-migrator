// FLEx List Migrator — landing page behavior.
// 1) Theme toggle (light/dark), shared with the FLET catalog via the same key.
// 2) Keep the download links and version label pointed at the newest release.

document.addEventListener('DOMContentLoaded', () => {
  const y = document.getElementById('year');
  if (y) y.textContent = new Date().getFullYear();

  // ── Theme toggle: cycles light/dark, persists choice, defaults to system.
  const btn = document.getElementById('theme-toggle');
  const root = document.documentElement;
  const systemDark = window.matchMedia('(prefers-color-scheme: dark)');
  const current = () => root.getAttribute('data-theme') || (systemDark.matches ? 'dark' : 'light');
  const updateLabel = () => {
    if (!btn) return;
    const next = current() === 'dark' ? 'light' : 'dark';
    btn.setAttribute('aria-label', 'Switch to ' + next + ' theme');
  };
  if (btn) {
    btn.addEventListener('click', () => {
      const next = current() === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('flet-theme', next); } catch (e) { /* ignore */ }
      updateLabel();
    });
    systemDark.addEventListener('change', updateLabel);
    updateLabel();
  }

  // ── Version label: the download buttons use GitHub's stable
  // /releases/latest/download/<asset> URL, which always resolves to the current
  // release — no JS needed for the link itself. We only fetch the release name
  // to show the version number. If the API call fails (offline, rate limit),
  // the hardcoded fallback text stays as-is.
  fetch('https://api.github.com/repos/rulingAnts/flex-list-migrator/releases/latest', {
    headers: { 'Accept': 'application/vnd.github+json' }
  })
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then((rel) => {
      const tag = rel && (rel.tag_name || rel.name);
      if (!tag) return;
      document.querySelectorAll('#version-label, #version-label-2').forEach((el) => {
        el.textContent = tag;
      });
    })
    .catch(() => { /* keep fallback label */ });
});
