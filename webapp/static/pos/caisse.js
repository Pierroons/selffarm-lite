// ============ État panier ============
const SESSION_ID = JSON.parse(document.getElementById('caisse-data').textContent).session_id;
let panier = {}; // {produitId: {nom, prix, unite, emoji, qte}}
let modePaiementSelected = null;

function fmtEur(n) { return n.toLocaleString('fr-FR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' €'; }

// Unités vendues AU POIDS → saisie décimale au clavier (balance, précision 0,001).
// Les autres (pièce, botte, douzaine, pot…) → incrément +1.
const UNITES_POIDS = ['kg', 'g', 'kilo', 'kilos', 'gramme', 'grammes', 'l', 'litre', 'litres'];
function estAuPoids(unite) {
  return UNITES_POIDS.includes((unite || '').toLowerCase().trim());
}

function demanderPoids(unite, nom, valeurActuelle) {
  const def = valeurActuelle ? String(valeurActuelle).replace('.', ',') : '';
  const raw = prompt(`Poids en ${unite} — ${nom}\n(décimales acceptées, ex : 1,250)`, def);
  if (raw === null) return null;
  const v = parseFloat(String(raw).replace(',', '.'));
  if (isNaN(v) || v < 0) { alert('Poids invalide.'); return null; }
  return Math.round(v * 1000) / 1000; // précision 0,001
}

function addToPanier(produitId) {
  const btn = document.querySelector(`.produit-btn[data-id="${produitId}"]`);
  if (!btn) return;
  const unite = btn.dataset.unite;
  if (!panier[produitId]) {
    panier[produitId] = {
      id: produitId,
      nom: btn.dataset.nom,
      prix: parseFloat(btn.dataset.prix),
      unite: unite,
      emoji: btn.dataset.emoji,
      qte: 0
    };
  }
  if (estAuPoids(unite)) {
    const v = demanderPoids(unite, panier[produitId].nom);
    if (v === null) { if (panier[produitId].qte === 0) delete panier[produitId]; renderPanier(); return; }
    panier[produitId].qte = Math.round((panier[produitId].qte + v) * 1000) / 1000; // cumul des pesées
    if (panier[produitId].qte <= 0) delete panier[produitId];
  } else {
    panier[produitId].qte += 1;
  }
  renderPanier();
}

function editPoids(produitId) {
  const l = panier[produitId];
  if (!l) return;
  const v = demanderPoids(l.unite, l.nom, l.qte);
  if (v === null) return;
  if (v <= 0) delete panier[produitId]; else l.qte = v;
  renderPanier();
}

function changerQte(produitId, delta) {
  if (!panier[produitId]) return;
  panier[produitId].qte += delta;
  if (panier[produitId].qte <= 0) delete panier[produitId];
  renderPanier();
}

function removeFromPanier(produitId) {
  delete panier[produitId];
  renderPanier();
}

function resetPanier() {
  panier = {};
  renderPanier();
}

function totalPanier() {
  return Object.values(panier).reduce((sum, l) => sum + l.prix * l.qte, 0);
}

function qtyCtrlHtml(l) {
  if (estAuPoids(l.unite)) {
    const poids = l.qte.toLocaleString('fr-FR', {minimumFractionDigits: 3, maximumFractionDigits: 3});
    return `<button type="button" data-action="edit-poids" data-id="${l.id}" title="Modifier le poids" style="background:transparent;border:1px dashed var(--accent-500);color:var(--text-primary);padding:4px 9px;border-radius:5px;cursor:pointer;font-size:12px;white-space:nowrap;">${poids} ${escapeHtml(l.unite)} ✎</button>`;
  }
  return `<button type="button" data-action="qte" data-id="${l.id}" data-delta="-1">−</button><span class="qty-val">${l.qte}</span><button type="button" data-action="qte" data-id="${l.id}" data-delta="1">+</button>`;
}

function renderPanier() {
  const body = document.getElementById('panierBody');
  const vide = document.getElementById('panierVide');
  const count = document.getElementById('panierCount');
  const total = document.getElementById('panierTotal');
  const btnEnc = document.getElementById('btnEncaisser');

  const lignes = Object.values(panier);
  count.textContent = lignes.length;

  if (lignes.length === 0) {
    body.innerHTML = '';
    vide.classList.add('show');
    total.textContent = '0,00 €';
    btnEnc.disabled = true;
    return;
  }

  vide.classList.remove('show');
  body.innerHTML = lignes.map(l => `
    <div class="panier-ligne">
      <span class="emo">${l.emoji || '🌿'}</span>
      <div class="info">
        <div class="nom-l">${escapeHtml(l.nom)}</div>
        <div class="meta-l">${fmtEur(l.prix)} / ${escapeHtml(l.unite)}</div>
      </div>
      <div class="qty-ctrl">${qtyCtrlHtml(l)}</div>
      <div class="ligne-total">${fmtEur(l.prix * l.qte)}</div>
      <button type="button" class="remove-btn" data-action="remove-panier" data-id="${l.id}" title="Retirer">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
  `).join('');

  total.textContent = fmtEur(totalPanier());
  btnEnc.disabled = false;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ============ Modal encaissement ============
function openModalEncaissement() {
  if (Object.keys(panier).length === 0) return;
  document.getElementById('modalTotal').textContent = fmtEur(totalPanier());
  modePaiementSelected = null;
  document.querySelectorAll('.payment-opt').forEach(o => o.classList.remove('selected'));
  document.getElementById('btnConfirmVente').disabled = true;
  document.getElementById('modalEncaissement').classList.add('open');
}

function closeModal() {
  document.getElementById('modalEncaissement').classList.remove('open');
}

function selectPayment(mode) {
  modePaiementSelected = mode;
  document.querySelectorAll('.payment-opt').forEach(o => {
    o.classList.toggle('selected', o.dataset.mode === mode);
  });
  document.getElementById('btnConfirmVente').disabled = false;
}

function confirmerVente() {
  if (!modePaiementSelected || Object.keys(panier).length === 0) return;
  const lignes = Object.values(panier).map(l => ({
    produit_id: l.id, nom: l.nom, emoji: l.emoji, prix: l.prix, unite: l.unite, qte: l.qte, total: l.prix * l.qte
  }));
  const total = totalPanier();
  const uuid = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : ('pos-' + Date.now() + '-' + Math.random().toString(36).slice(2));

  document.getElementById('lignes_json').value = JSON.stringify(lignes);
  document.getElementById('total_ttc').value = total.toFixed(2);
  document.getElementById('mode_paiement').value = modePaiementSelected;
  document.getElementById('offline_uuid').value = uuid;

  // Si offline → push queue + UI optimiste + sync ultérieure (registered ailleurs phase 3)
  if (!navigator.onLine) {
    queueVenteOffline({
      session_id: SESSION_ID, lignes, total_ttc: total,
      mode_paiement: modePaiementSelected, offline_uuid: uuid
    });
    onVenteEnregistree(total, modePaiementSelected);
    closeModal();
    resetPanier();
    return;
  }
  // En ligne : POST classique
  document.getElementById('formVente').submit();
}

function onVenteEnregistree(total, mode) {
  // Mise à jour optimiste affichage session
  const vEl = document.getElementById('sessionVentes');
  const tEl = document.getElementById('sessionTotal');
  vEl.textContent = (parseInt(vEl.textContent) || 0) + 1;
  tEl.textContent = fmtEur((parseFloat(tEl.textContent) || 0) + total);
}

// ============ Offline queue (Phase 3 wire) ============
function queueVenteOffline(payload) {
  const key = `pos-queue-${SESSION_ID}`;
  const queue = JSON.parse(localStorage.getItem(key) || '[]');
  queue.push(payload);
  localStorage.setItem(key, JSON.stringify(queue));
  console.info('[POS] Vente offline mise en queue', payload.offline_uuid);
}

async function flushOfflineQueue() {
  const key = `pos-queue-${SESSION_ID}`;
  const queue = JSON.parse(localStorage.getItem(key) || '[]');
  if (queue.length === 0) return;
  console.info(`[POS] Flush queue offline : ${queue.length} ventes`);
  try {
    const r = await fetch(`/api/pos/sessions/${SESSION_ID}/sync`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ventes: queue})
    });
    if (r.ok) {
      localStorage.removeItem(key);
      console.info('[POS] Queue offline vidée');
      // Rafraîchit la page pour voir les ventes synchronisées
      setTimeout(() => location.reload(), 800);
    }
  } catch (err) {
    console.warn('[POS] Flush queue échec :', err);
  }
}

// Online/offline indicator
function updateOnlineState() {
  const ind = document.getElementById('online-indicator');
  const lbl = document.getElementById('online-label');
  if (navigator.onLine) {
    ind.classList.remove('offline'); ind.classList.add('online');
    lbl.textContent = 'En ligne';
    flushOfflineQueue();
  } else {
    ind.classList.remove('online'); ind.classList.add('offline');
    lbl.textContent = 'Hors ligne';
  }
}
window.addEventListener('online', updateOnlineState);
window.addEventListener('offline', updateOnlineState);
window.addEventListener('load', updateOnlineState);

// Service worker + manifest PWA (Phase 3)
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/static/pos/sw.js', {scope: '/pos/'})
    .then((reg) => {
      // Background sync : flush automatique au retour connexion
      if ('sync' in reg) {
        reg.sync.register('flush-pos').catch(() => {});
      }
    })
    .catch(() => {});

  // Le SW peut nous notifier de flush la queue
  navigator.serviceWorker.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'flush-queue') {
      flushOfflineQueue();
    }
  });
}

SF.action('add-panier', (el) => addToPanier(Number(el.dataset.id)));
SF.action('reset-panier', () => resetPanier());
SF.action('open-encaissement', () => openModalEncaissement());
SF.action('close-modal', () => closeModal());
SF.action('close-modal-overlay', (el, e) => { if (e.target === el) closeModal(); });
SF.action('select-payment', (el) => selectPayment(el.dataset.mode));
SF.action('confirmer-vente', () => confirmerVente());
SF.action('edit-poids', (el) => editPoids(Number(el.dataset.id)));
SF.action('qte', (el) => changerQte(Number(el.dataset.id), Number(el.dataset.delta)));
SF.action('remove-panier', (el) => removeFromPanier(Number(el.dataset.id)));
