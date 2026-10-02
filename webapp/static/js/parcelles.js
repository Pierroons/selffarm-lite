// ===== Renommer une parcelle (édition inline) =====
function startRenameParcelle(id) {
  const cell = document.getElementById('nom-cell-' + id);
  if (!cell) return;
  const txt = cell.querySelector('.nom-text');
  const currentNom = txt.textContent.trim();
  cell.innerHTML = `
    <input type="text" class="nom-edit" id="nom-input-${id}" value="${escapeAttr(currentNom)}" maxlength="80">
    <span class="save-hint">↵ Sauver · Échap Annuler</span>
  `;
  const input = document.getElementById('nom-input-' + id);
  input.focus();
  input.select();
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); commitRename(id, currentNom); }
    else if (e.key === 'Escape') { e.preventDefault(); cancelRename(id, currentNom); }
  });
  input.addEventListener('blur', () => { commitRename(id, currentNom); });
}

async function commitRename(id, oldNom) {
  const input = document.getElementById('nom-input-' + id);
  if (!input) return;
  const newNom = input.value.trim();
  if (!newNom || newNom === oldNom) { cancelRename(id, oldNom); return; }
  const fd = new FormData();
  fd.append('nom', newNom);
  try {
    const r = await fetch(`/parcelles/${id}/rename`, { method: 'POST', body: fd });
    if (r.ok) {
      const data = await r.json();
      restoreNomCell(id, data.nom || newNom);
    } else {
      restoreNomCell(id, oldNom);
      alert('Erreur lors du renommage (HTTP ' + r.status + ')');
    }
  } catch (err) {
    restoreNomCell(id, oldNom);
    alert('Erreur réseau : ' + err.message);
  }
}

function cancelRename(id, oldNom) {
  restoreNomCell(id, oldNom);
}

function restoreNomCell(id, nom) {
  const cell = document.getElementById('nom-cell-' + id);
  if (!cell) return;
  cell.innerHTML = `
    <span class="nom-text">${escapeHtml(nom)}</span>
    <button type="button" class="pencil" title="Renommer cette parcelle" data-action="rename-parcelle" data-id="${id}">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
    </button>
  `;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function escapeAttr(s) {
  return String(s ?? '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

SF.action('rename-parcelle', (el) => startRenameParcelle(Number(el.dataset.id)));

// L'URL d'ajout d'une culture porte la parcelle choisie dans le formulaire.
const formCulture = document.getElementById('form-add-culture');
if (formCulture) {
  formCulture.addEventListener('submit', () => {
    formCulture.action = '/parcelles/' + formCulture.parcelle_id.value + '/culture/new';
  });
}
