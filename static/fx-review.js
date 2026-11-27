(() => {
  const form=document.querySelector('#fx-review-form');
  if (!form) return;
  const checks=[...form.querySelectorAll('input[name="selected"]')], all=form.querySelector('[data-select-all]');
  if (all && checks.length) {
    all.closest('label').hidden=false;
    all.addEventListener('change',()=>checks.forEach(c=>{c.checked=all.checked;}));
    form.addEventListener('change',()=>{all.checked=checks.every(c=>c.checked);all.indeterminate=!all.checked&&checks.some(c=>c.checked);});
  }
  // Preview in fixed-point arithmetic; the server validates and computes the actual publication.
  if (!window.BigInt) return;
  const scale=100000000n, fmt=new Intl.NumberFormat('fa-IR');
  function number(raw) {
    const text=raw.trim().replace(/[۰-۹]/g,c=>c.charCodeAt(0)-1776).replace(/[٠-٩]/g,c=>c.charCodeAt(0)-1632).replace(/٫/g,'.').replace(/٬/g,',');
    if (!/^(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,8})?$/.test(text) || text.length>40) throw Error();
    const [n,d='']=text.replace(/,/g,'').split('.');
    return BigInt(n)*scale+BigInt(d.padEnd(8,'0'));
  }
  form.addEventListener('input',event=>{
    const card=event.target.closest('.fx-card'), output=card?.querySelector('[data-output]');
    if (!output) return;
    const get=name=>card.querySelector(`[name$="-${name}"]`)?.value;
    try {
      const bid=number(get('basis_buy')),ask=number(get('basis_sell')??get('basis_buy')),extra=number(get('extra')),less=number(get('less'));
      if (card.hasAttribute('data-discount-required') && less===0n) {
        output.textContent='برای شارژ استارز، کسریِ خرید مثبت وارد کن.';
        return;
      }
      const pct=get('mode')==='percent', denom=pct?100n*scale*scale:scale;
      const low=pct?bid*(100n*scale-less):bid-less, high=pct?ask*(100n*scale+extra):ask+extra;
      if (ask<bid || low<denom || (!pct && (extra%scale || less%scale))) throw Error();
      output.textContent=`خرید ${fmt.format(low/denom)} · فروش ${fmt.format((high+denom-1n)/denom)} تومان`;
    } catch {output.textContent='مقادیر را بررسی کن';}
  });
})();
