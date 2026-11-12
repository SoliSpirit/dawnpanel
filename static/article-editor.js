(() => {
  const body = document.getElementById('id_body');
  if (!body) return;
  for (const button of document.querySelectorAll('[data-format]')) {
    button.addEventListener('click', () => {
      const status = document.getElementById('article-status');
      status.textContent = '';
      let {selectionStart: start, selectionEnd: end, value} = body;
      const selected = value.slice(start, end);
      let result = '**' + (selected || 'متن پررنگ') + '**';
      if (button.dataset.format === 'link') {
        const address = window.prompt('نشانی پیوند');
        if (address === null) return;
        try {
          const url = new URL(address);
          if (!['http:', 'https:'].includes(url.protocol)) throw new Error();
          result = '[' + (selected.replace(/[\]\n]/g, '').trim() || 'متن پیوند') + '](' + url.href.replace(/\)/g, '%29') + ')';
        } catch {
          status.textContent = 'نشانی معتبر با http یا https وارد کنید.';
          return;
        }
      } else if (button.dataset.format === 'heading') {
        start = start ? value.lastIndexOf('\n', start - 1) + 1 : 0;
        end = value.indexOf('\n', end);
        if (end < 0) end = value.length;
        result = '## ' + (value.slice(start, end).trim().replace(/^#{2,3} /, '') || 'عنوان بخش');
      }
      body.setRangeText(result, start, end, 'select');
      body.focus();
    });
  }
})();
