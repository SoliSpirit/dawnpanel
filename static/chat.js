(() => {
 const panel=document.getElementById('support-chat'), launcher=document.getElementById('chat-launcher');
 if(!panel||!launcher)return;
 const form=document.getElementById('chat-form'), input=document.getElementById('chat-body'), log=document.getElementById('chat-messages'), error=document.getElementById('chat-error'), presence=document.getElementById('chat-presence');
 let opened=false, busy=false, csrf='', after=0, timer, fetching=false, retryBody='', retryNonce='';
 const uuid=()=>crypto.randomUUID();
 async function request(options={}){
  const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),10000);
  try{const response=await fetch(panel.dataset.chatEndpoint,{credentials:'same-origin',cache:'no-store',...options,signal:controller.signal});const data=await response.json().catch(()=>({error:'ارتباط برقرار نشد؛ دوباره تلاش کنید.'}));if(!response.ok||data.error)throw Error(data.error||'دریافت پاسخ ممکن نشد.');return data;}finally{clearTimeout(timeout);}
 }
 function message(item){
  const bubble=document.createElement('article');bubble.className='chat-bubble '+(item.from_staff?'from-support':'from-customer');
  const name=document.createElement('strong');name.textContent=item.from_staff?'پشتیبانی دان پنل':'شما';
  const body=document.createElement('p');body.textContent=item.body;
  const time=document.createElement('time');time.dateTime=item.created_at;time.textContent=new Date(item.created_at).toLocaleTimeString('fa-IR',{hour:'2-digit',minute:'2-digit'});
  bubble.append(name,body,time);log.append(bubble);after=Math.max(after,item.id);
 }
 async function poll(){
  clearTimeout(timer);if(!opened||document.hidden||fetching)return;fetching=true;
  try{
   const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),10000);
   let response;try{response=await fetch(panel.dataset.chatEndpoint+'?after='+after,{credentials:'same-origin',cache:'no-store',signal:controller.signal});}finally{clearTimeout(timeout);}
   const data=await response.json().catch(()=>({error:'ارتباط برقرار نشد؛ دوباره تلاش کنید.'}));if(!response.ok||data.error)throw Error(data.error||'ارتباط برقرار نشد.');csrf=data.csrf;
   const nearBottom=log.scrollHeight-log.scrollTop-log.clientHeight<70;
   (data.messages||[]).forEach(message);if(nearBottom)log.scrollTop=log.scrollHeight;
   presence.textContent=data.online?'پشتیبان آنلاین است':'پیام بگذارید؛ پس از حضور پشتیبان پاسخ می‌دهیم.';presence.dataset.online=String(data.online);
   if(!busy)error.textContent=data.status==='closed'?'این گفتگو بسته شده؛ با پیام جدید دوباره باز می‌شود.':'';
  }catch(problem){error.textContent='ارتباط قطع شد؛ دوباره تلاش می‌کنیم.';}finally{fetching=false;if(opened&&!document.hidden)timer=setTimeout(poll,4000);}
 }
 function close(){opened=false;panel.hidden=true;launcher.setAttribute('aria-expanded','false');clearTimeout(timer);launcher.focus();}
 launcher.addEventListener('click',()=>{if(opened){close();return;}opened=true;panel.hidden=false;launcher.setAttribute('aria-expanded','true');input.focus({preventScroll:true});poll();});
 panel.querySelector('.chat-close').addEventListener('click',close);
 panel.addEventListener('keydown',event=>{if(event.key==='Escape')close();});
 document.addEventListener('visibilitychange',()=>{if(opened&&!document.hidden)poll();else clearTimeout(timer);});
 form.addEventListener('submit',async event=>{
  event.preventDefault();const body=input.value.trim();if(!body||busy)return;
  busy=true;input.disabled=true;form.querySelector('button').disabled=true;error.textContent='در حال ارسال…';
  if(retryBody!==body){retryBody=body;retryNonce=uuid();}
  try{if(!csrf){const data=await request();csrf=data.csrf;}
   await request({method:'POST',headers:{'X-CSRFToken':csrf},body:new URLSearchParams({body,nonce:retryNonce})});input.value='';retryBody='';error.textContent='';await poll();
  }catch(problem){error.textContent=problem.message||'پیام ارسال نشد؛ دوباره تلاش کنید.';}finally{busy=false;input.disabled=false;form.querySelector('button').disabled=false;}
 });
})();
