(() => {
 const carousel=document.querySelector('.shop-carousel');
 if(carousel){const slides=[...carousel.querySelectorAll('[data-slide]')],dots=[...carousel.querySelectorAll('[data-slide-to]')];let index=0;const show=next=>{index=(next+slides.length)%slides.length;slides.forEach((slide,i)=>slide.hidden=i!==index);dots.forEach((dot,i)=>dot.setAttribute('aria-pressed',String(i===index)));};carousel.addEventListener('click',event=>{const dot=event.target.closest('[data-slide-to]'),step=event.target.closest('[data-slide-step]');if(dot)show(Number(dot.dataset.slideTo));if(step)show(index+Number(step.dataset.slideStep));});}
 document.querySelectorAll('[data-rail]').forEach(button=>button.addEventListener('click',()=>{const rail=document.getElementById(button.dataset.rail);if(rail)rail.scrollBy({left:-Number(button.dataset.direction)*rail.clientWidth*.8,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});}));
 document.querySelectorAll('[data-open-chat]').forEach(button=>button.addEventListener('click',()=>{const launcher=document.getElementById('chat-launcher');if(launcher?.getAttribute('aria-expanded')!=='true')launcher?.click();}));
 document.addEventListener('keydown',event=>{if(event.key==='Escape')document.querySelectorAll('.category-menu[open]').forEach(menu=>menu.open=false);});
 document.addEventListener('click',event=>{document.querySelectorAll('.category-menu[open]').forEach(menu=>{if(!menu.contains(event.target))menu.open=false;});});
})();
