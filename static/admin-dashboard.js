(() => {
  'use strict';
  const period = document.getElementById('report-period');
  const dateFields = document.querySelector('.command-date-fields');
  period?.addEventListener('change', () => { dateFields.hidden = period.value !== 'custom'; });
  const data = document.getElementById('sales-chart-data');
  const host = document.getElementById('sales-visual');
  if (!data || !host) return;
  const rows = JSON.parse(data.textContent);
  const ns = 'http://www.w3.org/2000/svg';
  const make = (tag, attrs, text) => {
    const el = document.createElementNS(ns, tag);
    for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, String(value));
    if (text !== undefined) el.textContent = text;
    return el;
  };
  const number = new Intl.NumberFormat('fa-IR', {notation:'compact', maximumFractionDigits:1});
  const svg = make('svg', {viewBox:'0 0 760 230', 'aria-hidden':'true', focusable:'false'});
  const peak = Math.max(1, ...rows.map(r => r.amount));
  for (let i = 0; i <= 4; i++) {
    const y = 15 + i * 44;
    svg.append(make('line', {x1:64, y1:y, x2:750, y2:y, class:'chart-grid'}));
    svg.append(make('text', {x:53, y:y + 4, 'text-anchor':'end', class:'chart-axis'}, number.format(peak === 1 ? 0 : peak * (4-i)/4)));
  }
  const gap = 686 / Math.max(1, rows.length);
  rows.forEach((row, i) => {
    const height = row.amount / peak * 176;
    const x = 64 + i * gap;
    const group = make('g', {});
    group.append(make('title', {}, row.label + ': ' + new Intl.NumberFormat('fa-IR').format(row.amount) + ' تومان'));
    group.append(make('rect', {x:x + gap*.18, y:191 - Math.max(2,height), width:gap*.64, height:Math.max(2,height), rx:Math.min(5,gap*.1), class:row.amount ? 'chart-bar' : 'chart-zero'}));
    if (rows.length <= 8 || i === 0 || i === rows.length-1 || i % Math.ceil(rows.length/6) === 0) {
      svg.append(make('text', {x:x+gap/2, y:218, 'text-anchor':'middle', class:'chart-axis'}, row.label.slice(5)));
    }
    svg.append(group);
  });
  host.append(svg);
})();
