(() => {
  const amount = document.querySelector('[data-order-estimate]');
  const quantity = document.querySelector('.family-purchase input[type="number"][name="quantity"]');
  if (!amount || !quantity || typeof BigInt === 'undefined') return;
  const pack = BigInt(amount.dataset.pack);
  const unit = BigInt(amount.dataset.unit);
  const bps = BigInt(amount.dataset.taxBps);
  const subtotalLine = document.querySelector('[data-subtotal]');
  const taxLine = document.querySelector('[data-tax-amount]');
  if (pack <= 0n || unit <= 0n) return;
  const format = new Intl.NumberFormat('fa-IR');
  const render = (total, subtotal, tax) => {
    const show = value => value == null ? '—' : format.format(value);
    amount.textContent = show(total);
    if (subtotalLine) subtotalLine.textContent = show(subtotal);
    if (taxLine) taxLine.textContent = show(tax);
  };
  const update = () => {
    if (!quantity.validity.valid || !Number.isSafeInteger(quantity.valueAsNumber)) {
      render();
      return;
    }
    const subtotal = (BigInt(quantity.valueAsNumber) * pack + unit - 1n) / unit;
    const tax = (subtotal * bps + 9999n) / 10000n;
    const total = subtotal + tax;
    if (total > 0n && total <= 100000000000n) render(total, subtotal, tax);
    else render();
  };
  quantity.addEventListener('input', update);
  update();
})();
