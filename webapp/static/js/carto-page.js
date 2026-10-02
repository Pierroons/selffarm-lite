// Reçoit la notification d'ajout depuis l'iframe IGN
window.addEventListener('message', (event) => {
  if (event.origin !== window.location.origin) return;
  if (!event.data || event.data.type !== 'parcelle-added') return;
  const toast = document.getElementById('toast-add');
  const msg = document.getElementById('toast-add-msg');
  msg.textContent = `✓ Parcelle ${event.data.nom} ajoutée (${event.data.surface_ha.toFixed(3)} ha)`;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 6000);
});
