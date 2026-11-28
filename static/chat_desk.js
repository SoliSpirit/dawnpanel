(() => {
  const desk=document.getElementById('chat-desk');if(!desk)return;
  const el=id=>document.getElementById(id), list=el('desk-conversations'),log=el('desk-messages'),title=el('desk-title'),
    form=el('desk-form'),input=el('desk-body'),error=el('desk-error'),close=el('desk-close-thread'),send=form.querySelector('button');
  const csrf=form.querySelector('[name=csrfmiddlewaretoken]').value,base=desk.dataset.listUrl,fmt=new Intl.NumberFormat('fa-IR');
  let selected=desk.dataset.initialThread||null,after=0,ack=0,page=1,loading=false,again=false,busy=false,timer,heartbeat=0,retryBody='',retryNonce='';
  const changed=()=>document.dispatchEvent(new Event('dawn:desk-changed'));
  async function api(url,body){
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),10000);
    try{
      const response=await fetch(url,{credentials:'same-origin',cache:'no-store',signal:controller.signal,
        ...(body?{method:'POST',headers:{'X-CSRFToken':csrf},body:new URLSearchParams(body)}:{})});
      const data=await response.json().catch(()=>({error:'ارتباط با میز گفتگو برقرار نشد.'}));
      if(!response.ok||data.error)throw Error(data.error||'دریافت گفتگو ناموفق بود.');return data;
    }finally{clearTimeout(timeout);}
  }
  function controls(on){input.disabled=send.disabled=close.disabled=!on;}
  function select(row){
    if(busy)return;
    selected=row.id;after=ack=0;log.replaceChildren();input.value=retryBody=retryNonce='';title.textContent=row.label;
    controls(true);refresh();
  }
  function messages(items){
    const nearBottom=log.scrollHeight-log.scrollTop-log.clientHeight<80;
    for(const item of items){
      const article=document.createElement('article'),name=document.createElement('strong'),body=document.createElement('p'),time=document.createElement('time');
      article.className='chat-bubble '+(item.from_staff?'from-support':'from-customer');
      name.textContent=item.from_staff?'پشتیبان':'بازدیدکننده';body.textContent=item.body;
      time.textContent=new Date(item.created_at).toLocaleTimeString('fa-IR',{hour:'2-digit',minute:'2-digit'});
      article.append(name,body,time);log.append(article);after=Math.max(after,item.id);
    }
    if(nearBottom)log.scrollTop=log.scrollHeight;
  }
  async function refresh(){
    if(document.hidden)return;if(loading){again=true;return;}clearTimeout(timer);loading=true;
    try{
      if(Date.now()-heartbeat>25000){await api(base,{});heartbeat=Date.now();}
      const currentPage=page,data=await api(base+'?page='+currentPage),nodes=[];
      if(currentPage!==page){again=true;return;}
      for(const row of data.conversations){
        const b=document.createElement('button'),heading=document.createElement('strong'),preview=document.createElement('span'),badge=document.createElement('small');
        b.type='button';b.className='desk-conversation'+(selected===row.id?' selected':'');b.dataset.waiting=String(row.status==='waiting');
        heading.textContent=row.label;preview.textContent=row.preview;
        badge.textContent=(row.unread?`${fmt.format(row.unread)} پیام خوانده‌نشده · `:'')+({waiting:'منتظر پاسخ',open:'در گفتگو',closed:'بسته'}[row.status]||'');
        b.append(heading,preview,badge);b.onclick=()=>select(row);nodes.push(b);
        if(selected===row.id)title.textContent=row.label;
      }
      if(!nodes.length){const p=document.createElement('p');p.textContent='هنوز پیامی دریافت نشده است.';nodes.push(p);}
      for(const [show,step,label] of [[page>1,-1,'صفحهٔ قبل'],[data.more,1,'صفحهٔ بعد']]){
        if(show){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=()=>{page=currentPage+step;refresh();};nodes.push(b);}
      }
      list.replaceChildren(...nodes);el('desk-count').textContent=fmt.format(data.unread);
      if(selected){
        const current=selected,thread=await api(base+current+'/?after='+after);
        if(selected===current){
          messages(thread.messages);if(!busy)controls(true);
          if(after>ack&&!document.hidden){
            const through=after;await api(base+current+'/',{action:'read',through});
            if(selected===current){ack=through;changed();}
          }
          if(thread.messages.length===100)again=true;
        }
      }
      if(!busy)error.textContent='';
    }catch(e){error.textContent=e.message||'ارتباط برقرار نشد.';}
    finally{loading=false;if(!document.hidden)timer=setTimeout(refresh,again?0:4000);again=false;}
  }
  form.addEventListener('submit',async e=>{
    e.preventDefault();const body=input.value.trim();if(busy||!selected||!body)return;
    busy=true;controls(false);if(retryBody!==body){retryBody=body;retryNonce=crypto.randomUUID();}
    try{await api(base+selected+'/',{body,nonce:retryNonce});input.value=retryBody='';changed();refresh();}
    catch(e){error.textContent=e.message;}finally{busy=false;controls(true);}
  });
  close.onclick=async()=>{if(!selected||busy)return;busy=true;controls(false);
    try{await api(base+selected+'/',{action:'close'});changed();refresh();}
    catch(e){error.textContent=e.message;}finally{busy=false;controls(true);}
  };
  document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);else refresh();});refresh();
})();
