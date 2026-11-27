(() => {
  const form = document.getElementById('changelist-form');
  if (!form) return;
  const table = document.getElementById('result_list');
  document.getElementById('searchbar')?.setAttribute('placeholder', 'جستجو در این فهرست…');
  // Labeled cards keep every control in reach on a phone. Sorting and Django's
  // native selection/action controls must remain available in this layout too.
  if (table?.tHead && table.tBodies[0]) {
    const headers = Array.from(table.tHead.rows[0].cells);
    const names = headers.map(h => h.querySelector('.text')?.textContent.trim() || '');
    for (const row of table.tBodies[0].rows) {
      const title = row.querySelector('.field-product_label') || row.querySelector('th');
      title?.classList.add('dp-card-title');
      for (const cell of row.cells) {
        if (cell === title || cell.classList.contains('action-checkbox')) continue;
        const label = document.createElement('span');
        label.className = 'dp-cell-heading';
        label.textContent = names[cell.cellIndex]; cell.prepend(label);
      }
    }
    const selectAll = table.querySelector('#action-toggle');
    if (selectAll) {
      const label = document.createElement('label');
      label.className = 'dp-card-select-all'; label.htmlFor = selectAll.id;
      label.textContent = 'انتخاب همهٔ ردیف‌های این صفحه';
      selectAll.closest('th').append(label); table.classList.add('dp-has-actions');
    }
    const sorts = document.createElement('details'), summary = document.createElement('summary');
    sorts.className = 'dp-mobile-sort'; summary.textContent = 'مرتب‌سازی'; sorts.append(summary);
    const links = document.createElement('div');
    for (const header of headers) {
      const primary = header.querySelector('.text a');
      if (!primary) continue;
      const link = primary.cloneNode(true);
      if (header.classList.contains('sorted')) {
        link.setAttribute('aria-current','true');
        link.append(header.querySelector('.descending') ? ' ↓' : ' ↑');
      }
      links.append(link);
    }
    if (links.childElementCount) {
      sorts.append(links); document.querySelector('.dp-list-controls')?.append(sorts);
    }
    table.classList.add('dp-card-mode');
  }

  const flash = document.querySelector('.dp-state-flash');
  if (!flash || !window.fetch || !window.AbortController || !window.SubmitEvent || !('submitter' in SubmitEvent.prototype)) return;
  const token = form.querySelector('input[name="csrfmiddlewaretoken"]')?.value;
  if (!token) return;
  let timer;
  const notify = (message, error, reload=false) => {
    window.clearTimeout(timer);
    flash.hidden = false; flash.classList.toggle('error', error);
    flash.querySelector('[data-flash-text]').textContent = message;
    flash.querySelector('[data-flash-reload]').hidden = !reload;
    if (!error) timer = window.setTimeout(() => { flash.hidden = true; }, 4500);
  };
  flash.querySelector('[data-flash-close]').addEventListener('click', () => {flash.hidden = true;});
  const show = (button, on) => {
    button.setAttribute('aria-checked', String(on));
    button.value = button.value.slice(0, -1) + (on ? '0' : '1');
    button.querySelector('.dp-state-label').textContent = on ? button.dataset.on : button.dataset.off;
  };
  form.addEventListener('submit', async event => {
    const b = event.submitter;
    if (!b?.matches('button[name="_dp_state"]')) return;
    if (b.getAttribute('aria-disabled') === 'true') { event.preventDefault(); return; }
    // A bulk-actions select named "action" shadows HTMLFormElement.action.
    const url = new URL(form.getAttribute('action') || location.href, location.href);
    // A changed filter/sort key could move the row to a different page. Let the
    // native POST/redirect rebuild the results rather than leaving stale counts.
    const field = b.value.split(':')[1];
    if (url.searchParams.has('o') || url.searchParams.has('_facets') || url.searchParams.has(field+'__exact') || url.searchParams.has(field)) return;
    event.preventDefault();
    const label = b.querySelector('.dp-state-label'), desired = b.value.endsWith(':1');
    const ctl = new AbortController(), timeout = window.setTimeout(() => ctl.abort(), 15000);
    b.setAttribute('aria-disabled','true'); b.setAttribute('aria-busy','true'); label.textContent='در حال ذخیره…';
    const recover = message => {
      b.dataset.uncertain=''; b.removeAttribute('aria-checked'); b.removeAttribute('aria-disabled');
      b.removeAttribute('role'); b.type='button'; label.textContent='بازخوانی وضعیت';
      b.setAttribute('aria-label', 'بازخوانی وضعیت: '+b.getAttribute('aria-label'));
      b.addEventListener('click', () => location.assign(url.href), {once:true});
      notify(message, true, true);
    };
    try {
      const response = await fetch(url, {method:'POST', mode:'same-origin', credentials:'same-origin', redirect:'error',
        headers:{Accept:'application/json'}, body:new URLSearchParams({csrfmiddlewaretoken:token,_dp_state:b.value}),
        signal:ctl.signal});
      if ([403,404].includes(response.status)) {
        recover('این ردیف دیگر از این صفحه قابل ویرایش نیست. فهرست را دوباره باز کن.'); return;
      }
      if (!response.headers.get('Content-Type')?.includes('application/json')) throw Error();
      const data = await response.json();
      if (!data.message) throw Error();
      if (!response.ok && data.checked === null) { recover(data.message); return; }
      if (typeof data.checked !== 'boolean' || (response.ok && data.checked!==desired)) throw Error();
      show(b, data.checked); b.removeAttribute('aria-disabled');
      notify(data.message, !response.ok);
    } catch {
      // The server may have committed before a lost response. Don't claim the
      // previous or the new value is saved, and don't send another write blindly.
      recover('وضعیت نهایی تأیید نشد. فهرست را دوباره باز کن تا وضعیت ذخیره‌شده را ببینی.');
    } finally {
      window.clearTimeout(timeout); b.removeAttribute('aria-busy');
    }
  });
})();
