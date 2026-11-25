(() => {
  const rail = document.querySelector('#workspace-rail');
  const toggle = document.querySelector('.dp-rail-toggle');
  for (const selected of document.querySelectorAll('.dp-nav-group [aria-current]')) selected.closest('details').open = true;
  // Native disclosures still work without JavaScript, including the mobile menu.
  for (const menu of document.querySelectorAll('details[name="admin-header-menus"]')) {
    document.addEventListener('click', event => { if (menu.open && !menu.contains(event.target)) menu.open = false; });
    menu.addEventListener('keydown', event => {
      if (event.key === 'Escape' && menu.open) { menu.open = false; menu.querySelector('summary').focus(); }
    });
  }
  if (!rail || !toggle) return;
  const key = 'dawnpanel-admin-rail';
  let open = true;
  try { open = localStorage.getItem(key) !== 'closed'; } catch {}
  const setOpen = state => {
    open = state; rail.hidden = !state;
    toggle.setAttribute('aria-expanded', String(state));
  };
  toggle.hidden = false; setOpen(open);
  toggle.addEventListener('click', () => {
    setOpen(!open);
    try { localStorage.setItem(key, open ? 'open' : 'closed'); } catch {}
  });
  const input = rail.querySelector('input');
  const groups = [...rail.querySelectorAll('.dp-nav-group')];
  let saved;
  const normalize = str => str.toLowerCase().normalize('NFKC').replaceAll('ي','ی').replaceAll('ك','ک').replace(/[\s\u200c]+/g, ' ').trim();
  const filter = () => {
    const q = normalize(input.value);
    if (q && !saved) saved = groups.map(group => group.open);
    let matches = 0;
    for (const link of rail.querySelectorAll('.dp-nav-link')) {
      const group = link.closest('details');
      const text = link.textContent + ' ' + (group?.querySelector('summary').textContent || '');
      link.hidden = !!q && !normalize(text).includes(q);
      if (!link.hidden) matches++;
    }
    groups.forEach((group, index) => {
      group.hidden = !!q && !group.querySelector('a:not([hidden])');
      if (q) group.open = !group.hidden;
      else if (saved) group.open = saved[index];
    });
    if (!q) saved = undefined;
    rail.querySelector('.dp-no-results').hidden = !q || matches !== 0;
  };
  input.addEventListener('input', filter);
  input.addEventListener('keydown', event => { if (event.key === 'Escape') { input.value = ''; filter(); } });
})();
