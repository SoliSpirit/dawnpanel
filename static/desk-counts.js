(() => {
  const endpoint=document.currentScript?.dataset.deskEndpoint;
  if (!endpoint || !document.querySelector('[data-desk-count]')) return;
  const fmt=new Intl.NumberFormat('fa-IR');
  let last=null,busy=false,timer,stopped=false;
  const flash=document.createElement('div'),link=document.createElement('a'),close=document.createElement('button');
  flash.className='desk-chat-flash';flash.hidden=true;flash.setAttribute('role','status');
  link.href=new URL('../chat/',new URL(endpoint,location.href)).href;
  close.type='button';close.textContent='بستن';close.onclick=()=>{flash.hidden=true;};
  flash.append(link,close);document.body.append(flash);
  async function poll(){
    if(busy||stopped||document.hidden)return;busy=true;clearTimeout(timer);
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),10000);
    try{
      const res=await fetch(endpoint,{credentials:'same-origin',cache:'no-store',signal:controller.signal});
      if([401,403,404].includes(res.status)){
        stopped=true;flash.hidden=true;document.querySelectorAll('[data-desk-count]').forEach(b=>b.hidden=true);return;
      }
      if(!res.ok)return;
      const report=await res.json();
      document.querySelectorAll('[data-desk-count]').forEach(b=>{
        const n=report[b.dataset.deskCount]||0;b.textContent=fmt.format(n);b.hidden=!n;
      });
      if(report.chat>0 && last!==null && report.latest>last){
        link.textContent=`پیام تازه در چت سایت · ${fmt.format(report.chat)} پیام خوانده‌نشده`;flash.hidden=false;
      }
      if(!report.chat)flash.hidden=true;
      last=report.latest??null;
    } catch {} finally {clearTimeout(timeout);busy=false;if(!stopped&&!document.hidden)timer=setTimeout(poll,10000);}
  }
  document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);else poll();});
  document.addEventListener('dawn:desk-changed',poll);poll();
})();
