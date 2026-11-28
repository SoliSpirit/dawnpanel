for(const form of document.querySelectorAll('.op-pref')) {
  const mirror=form.querySelector('[data-mirror]');
  if(mirror){mirror.hidden=false;mirror.addEventListener('click',()=>{
    const on=new Set([...form.querySelectorAll('[name=topics]:checked')].map(el=>el.value));
    form.querySelectorAll('[name=email_topics]').forEach(el=>el.checked=on.has(el.value));
  });}
}
for(const form of document.querySelectorAll('.fin-toolbar')){
  const period=form.querySelector('[name=period]');
  const sync=()=>form.querySelectorAll('input[type=date]').forEach(el=>{el.closest('label').hidden=el.disabled=period.value!=='custom';});
  period.addEventListener('change',sync);sync();
}
for(const el of document.querySelectorAll('[data-price-preview]')){
  const input=el.form?.elements.markup||el.closest('form')?.elements.markup;
  if(!input)continue;
  const update=()=>{
    const v=input.value.replace(/[۰-۹]/g,c=>String(c.charCodeAt(0)-1776)).replace('٫','.');
    if(!/^\d{1,6}(?:\.\d{1,4})?$/.test(v)){el.textContent='—';return;}
    const [n,f='']=v.split('.'),basis=BigInt(n)*10000n+BigInt(f.padEnd(4,'0'));
    el.textContent=new Intl.NumberFormat('fa-IR').format((BigInt(el.dataset.pricePreview)*(1000000n+basis)+999999n)/1000000n)+' تومان';
  };input.addEventListener('input',update);update();
}
