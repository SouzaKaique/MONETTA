// Aplica o tema antes do primeiro desenho, evitando um clarão no modo escuro.
// Fica em arquivo próprio porque a política de segurança proíbe scripts inline.
(function () {
  var pref = 'system';
  try { pref = localStorage.getItem('monetta-theme') || 'system'; } catch (e) {}
  var dark = pref === 'dark' || (pref === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.setAttribute('data-bs-theme', dark ? 'dark' : 'light');
})();
