/* Decorative libraries load only after interaction on devices that use them. */
(() => {
  const entry=document.currentScript?.dataset.storefrontSrc;
  if(!entry || matchMedia('(prefers-reduced-motion: reduce)').matches || !matchMedia('(hover: hover) and (pointer: fine)').matches)return;
  let loaded=false;
  const events=['pointerdown','keydown','wheel'];
  function load(){
    if(loaded)return;loaded=true;
    events.forEach(name=>window.removeEventListener(name,load));
    const start=()=>{const script=document.createElement('script');script.src=entry;script.async=true;document.head.append(script);};
    if('requestIdleCallback' in window)requestIdleCallback(start,{timeout:1500});else setTimeout(start,0);
  }
  events.forEach(name=>window.addEventListener(name,load,{passive:true}));
})();
