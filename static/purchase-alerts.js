(() => {
  const panel = document.querySelector('[data-order-alerts]');
  if (!panel) return;
  const button = panel.querySelector('[data-enable-alerts]'), status = panel.querySelector('[data-alert-status]');
  const list = panel.querySelector('[data-recent-alerts]'), format = new Intl.NumberFormat('fa-IR');
  let seen = new Set(), initialized = false, timer, busy = false, stopped = false;
  const supported = 'Notification' in window && window.isSecureContext;
  let enabled = false;
  try { enabled = localStorage.getItem('dawn.purchase-alerts') === 'on'; } catch {}
  function buttonLabel() {
    button.hidden = !supported || Notification.permission === 'denied';
    button.textContent = enabled && Notification.permission === 'granted' ? 'خاموش‌کردن اعلان مرورگر' : 'فعال‌کردن اعلان مرورگر';
  }
  if (supported) {
    buttonLabel();
    button.addEventListener('click', async () => {
      try {
        enabled = enabled && Notification.permission === 'granted' ? false : (await Notification.requestPermission()) === 'granted';
        localStorage.setItem('dawn.purchase-alerts', enabled ? 'on' : 'off');
      } catch { enabled = false; }
      buttonLabel();
      status.textContent = enabled ? 'اعلان مرورگر تا وقتی داشبورد باز است فعال است.' : 'اعلان مرورگر خاموش است؛ خریدها در همین فهرست دیده می‌شوند.';
    });
  }
  function show(order) {
    if (!supported || !enabled || Notification.permission !== 'granted') return;
    try {
      const n = new Notification(`سفارش جدید از ${order.channel}`, {body: order.tracking, tag:`dawn-order-${order.id}`});
      n.onclick = () => { window.focus(); location.assign(order.url); n.close(); };
    } catch {} // Some mobile browsers only support service-worker notifications.
  }
  async function poll() {
    if (busy || stopped) return;
    clearTimeout(timer);
    busy = true;
    try {
      const response = await fetch(panel.dataset.orderAlerts, {credentials:'same-origin',cache:'no-store'});
      if ([401,403,404].includes(response.status)) {
        stopped = true; list.replaceChildren(); status.textContent='برای دیدن اعلان‌ها دوباره وارد مدیریت شوید.'; return;
      }
      if (!response.ok) throw Error();
      const {orders} = await response.json(), fragment = document.createDocumentFragment();
      const fresh = orders.filter(o => initialized && !seen.has(o.id));
      for (const o of orders.slice(0,5)) {
        const li=document.createElement('li'), a=document.createElement('a');
        a.href=o.url; a.textContent=`${o.channel} · ${o.product} · ${format.format(o.amount)} تومان · ${o.tracking}`;
        li.append(a); fragment.append(li);
      }
      list.replaceChildren(fragment);
      if (fresh.length) {
        status.textContent=`${format.format(fresh.length)} سفارش جدید؛ آخرین خرید از ${fresh[0].channel}.`;
        show(fresh[0]);
      } else if (!initialized) {
        status.textContent=orders.length ? 'آخرین خریدهای ثبت‌شده از سایت و ربات' : 'در انتظار خرید بعدی از سایت یا ربات';
      }
      seen = new Set(orders.map(o => o.id)); initialized=true;
    } catch { status.textContent='ارتباط با فهرست اعلان‌ها برقرار نشد؛ دوباره تلاش می‌شود.'; }
    finally { busy=false; if (!stopped) timer=setTimeout(poll,document.hidden ? 30000 : 12000); }
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  poll();
})();
