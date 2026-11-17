(() => {
  const amount = document.querySelector('[data-order-estimate]');
  const quantity = document.querySelector('.family-purchase input[type="number"][name="quantity"]');
  if (!amount || !quantity || typeof BigInt === 'undefined') return;
  const pack = BigInt(amount.dataset.pack);
  const unit = BigInt(amount.dataset.unit);
  if (pack <= 0n || unit <= 0n) return;
  const format = new Intl.NumberFormat('fa-IR');
  const update = () => {
    if (!quantity.validity.valid || !Number.isSafeInteger(quantity.valueAsNumber)) {
      amount.textContent = '—';
      return;
    }
    const total = (BigInt(quantity.valueAsNumber) * pack + unit - 1n) / unit;
    amount.textContent = total > 0n && total <= 100000000000n ? format.format(total) : '—';
  };
  quantity.addEventListener('input', update);
  update();
})();
