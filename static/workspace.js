(() => {
  const input = document.getElementById('nav-filter');
  if (!input) return;
  const groups = document.querySelectorAll('.workspace-nav-group');
  const filter = () => {
    const query = input.value.trim().toLocaleLowerCase();
    for (const group of groups) {
      let count = 0;
      for (const link of group.querySelectorAll('a')) {
        link.hidden = !!query && !link.textContent.toLocaleLowerCase().includes(query);
        if (!link.hidden) count++;
      }
      group.hidden = count === 0;
      if (query && count) group.open = true;
    }
  };
  input.addEventListener('input', filter);
  input.addEventListener('keyup', filter);
  filter();
})();
