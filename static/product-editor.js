(() => {
  'use strict';
  const form = document.getElementById('product_form');
  if (!form) return;
  const field = name => form.elements.namedItem(name);
  const text = (id, value) => { document.getElementById(id).textContent = value; };
  const number = new Intl.NumberFormat('fa-IR');
  function update() {
    text('editor-preview-name', field('name').value.trim() || 'نام محصول شما');
    const price = Number(field('price').value);
    text('editor-preview-price', price > 0 ? `${number.format(price)} تومان · قیمت پایه` : 'قیمت پایه را وارد کنید');
    text('editor-preview-unit', `به‌ازای ${number.format(Number(field('price_per').value) || 1)} عدد`);
    text('editor-preview-platform', field('platform').selectedOptions[0]?.textContent || 'محصول دیجیتال');
    const list = document.getElementById('editor-preview-channels');
    const labels = field('is_active').checked
      ? [['show_on_website', 'فروشگاه سایت'], ['show_on_telegram', 'ربات تلگرام']].filter(([name]) => field(name).checked).map(([,label]) => label)
      : ['غیرفعال؛ خرید متوقف است'];
    list.replaceChildren(...(labels.length ? labels : ['هیچ محل نمایشی انتخاب نشده']).map(label => {
      const item = document.createElement('li'); item.textContent = label; return item;
    }));
  }
  const previewImage = document.getElementById('editor-preview-image');
  const placeholder = previewImage.src;
  let previewVersion = 0;
  function updateImage() {
    const version = ++previewVersion;
    const night = document.documentElement.dataset.theme === 'dark';
    const chosen = field(night ? 'night_picture' : 'picture').files[0];
    const existing = document.querySelector(night ? '.field-current_night_picture img' : '.field-current_picture img');
    const image = document.getElementById('editor-preview-image');
    if (chosen && chosen.size <= 5 * 1024 * 1024 && /^image\/(jpeg|png|webp)$/.test(chosen.type)) {
      const reader = new FileReader();
      reader.onload = () => { if (previewVersion === version) image.src = reader.result; };
      reader.readAsDataURL(chosen);
    } else image.src = existing ? existing.src : placeholder.replace('social-light-480.webp', night ? 'social-480.webp' : 'social-light-480.webp');
  }
  form.addEventListener('input', update);
  form.addEventListener('change', event => { update(); if (event.target.type === 'file') updateImage(); });
  new MutationObserver(updateImage).observe(document.documentElement, {attributes:true,attributeFilter:['data-theme']});
  update(); updateImage();
})();
