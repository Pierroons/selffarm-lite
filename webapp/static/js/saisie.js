// Aperçu du TTC en direct — évite la calculette mentale à la saisie.
(function () {
  const ht = document.getElementById('montant_ht');
  const tva = document.getElementById('taux_tva');
  const out = document.getElementById('ttc-valeur');
  function maj() {
    const h = parseFloat((ht.value || '').replace(',', '.'));
    const t = parseFloat(tva.value || '0');
    if (isNaN(h) || h <= 0) { out.textContent = '—'; return; }
    out.textContent = (h * (1 + t / 100)).toFixed(2).replace('.', ',') + ' €';
  }
  ht.addEventListener('input', maj);
  tva.addEventListener('change', maj);
  maj();
})();
