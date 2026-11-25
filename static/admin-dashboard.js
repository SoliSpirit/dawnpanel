(() => {
  const host = document.getElementById('sales-visual');
  if (!host) return;
  const rows = JSON.parse(document.getElementById('sales-chart-data').textContent);
  if (!rows.length) return;
  const svgNS = 'http://www.w3.org/2000/svg';
  const el = (kind, attrs = {}, text) => {
    const node = document.createElementNS(svgNS, kind);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const compact = new Intl.NumberFormat('fa-IR', {notation:'compact', maximumFractionDigits:1});
  const full = new Intl.NumberFormat('fa-IR');
  let lastWidth;
  function draw() {
    const w = Math.floor(host.clientWidth);
    if (w < 100 || w === lastWidth) return;
    lastWidth = w;
    const h = w < 460 ? 155 : 182;
    const left = w < 400 ? 46 : 62, right = w - 18, top = 15, bottom = h - 27;
    const peak = Math.max(1, ...rows.map(r => r.amount));
    const scale = 10 ** Math.floor(Math.log10(peak/3));
    const step = Math.max(1, [1,2,5,10].find(n => n*scale >= peak/3)*scale);
    const ceiling = Math.ceil(peak/step)*step;
    const x = i => rows.length === 1 ? (left+right)/2 : left + i*(right-left)/(rows.length-1);
    const y = v => bottom - (v/ceiling)*(bottom-top);
    const svg = el('svg', {viewBox:`0 0 ${w} ${h}`, direction:'ltr', 'aria-hidden':'true', focusable:'false'});
    const defs = el('defs'), grad = el('linearGradient', {id:'desk-chart-fill',x1:0,x2:0,y1:0,y2:1});
    grad.append(el('stop', {offset:0,class:'area-stop','stop-opacity':.28}),el('stop',{offset:1,class:'area-stop','stop-opacity':.02}));
    defs.append(grad); svg.append(defs);
    for (let v=0; v<=ceiling; v+=step) {
      svg.append(el('line',{x1:left,x2:right,y1:y(v),y2:y(v),class:'grid'}),
                 el('text',{x:left-6,y:y(v)+4,'text-anchor':'end'},compact.format(v)));
    }
    const pts = rows.map((r,i) => [x(i),y(r.amount)]);
    if (pts.length > 1) {
      const path = 'M' + pts.map(p=>p.join(',')).join(' L');
      svg.append(el('path',{d:`${path} L${right},${bottom} L${left},${bottom} Z`,fill:'url(#desk-chart-fill)'}),
                 el('path',{d:path,class:'trend'}));
    }
    const ticks = Math.max(2,Math.floor((right-left)/82));
    const tickIndexes = new Set(Array.from({length:ticks},(_,n)=>Math.round(n*(rows.length-1)/(ticks-1))));
    pts.forEach(([px,py],i) => {
      if (pts.length<=14 || i===pts.length-1) svg.append(el('circle',{cx:px,cy:py,r:3.5,class:'point'}));
      if (tickIndexes.has(i)) svg.append(el('text',{x:Math.min(w-32,Math.max(33,px)),y:h-6,direction:'rtl','text-anchor':'middle'},rows[i].tick));
      const a=i ? (px+x(i-1))/2 : left, b=i===pts.length-1 ? right : (px+x(i+1))/2;
      const hit=el('rect',{x:a,y:top,width:b-a,height:bottom-top,fill:'transparent'});
      hit.append(el('title',{},`${rows[i].display}: ${full.format(rows[i].amount)} تومان`)); svg.append(hit);
    });
    host.replaceChildren(svg);
  }
  draw();
  if ('ResizeObserver' in window) new ResizeObserver(draw).observe(host);
  else window.addEventListener('resize',draw);
})();
