const APP_VERSION = document.body.dataset.version;

// ============================================================
// SelfPOS Mobile PWA — Single-page vanilla JS + IndexedDB
// ============================================================

const DB_NAME = 'selfpos-mobile';
const DB_VERSION = 2;
const STORES = ['catalogue', 'sessions', 'ventes', 'chargement', 'residus', 'settings', 'backups'];

// ============ IndexedDB wrapper minimaliste (promises) ============
let dbInstance = null;
function openDB() {
  if (dbInstance) return Promise.resolve(dbInstance);
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains('catalogue'))
        db.createObjectStore('catalogue', { keyPath: 'id' });
      if (!db.objectStoreNames.contains('sessions'))
        db.createObjectStore('sessions', { keyPath: 'local_id', autoIncrement: true });
      if (!db.objectStoreNames.contains('ventes')) {
        const s = db.createObjectStore('ventes', { keyPath: 'offline_uuid' });
        s.createIndex('session', 'session_local_id', { unique: false });
      }
      if (!db.objectStoreNames.contains('chargement')) {
        const s = db.createObjectStore('chargement', { keyPath: ['session_local_id', 'produit_id'] });
      }
      if (!db.objectStoreNames.contains('residus')) {
        const s = db.createObjectStore('residus', { keyPath: ['session_local_id', 'produit_id'] });
      }
      if (!db.objectStoreNames.contains('settings'))
        db.createObjectStore('settings', { keyPath: 'key' });
      if (!db.objectStoreNames.contains('backups'))
        db.createObjectStore('backups', { keyPath: 'sha' });
    };
    req.onsuccess = () => { dbInstance = req.result; resolve(dbInstance); };
    req.onerror = () => reject(req.error);
  });
}

async function dbPut(storeName, value) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readwrite');
    const req = tx.objectStore(storeName).put(value);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function dbGet(storeName, key) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readonly');
    const req = tx.objectStore(storeName).get(key);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function dbGetAll(storeName) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readonly');
    const req = tx.objectStore(storeName).getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function dbDelete(storeName, key) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readwrite');
    const req = tx.objectStore(storeName).delete(key);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

async function dbClear(storeName) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readwrite');
    const req = tx.objectStore(storeName).clear();
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

// ============ App state ============
const app = {
  currentScreen: 'caisse',
  catalogue: [],
  visibility: {}, // produit_id → bool
  currentSession: null, // session locale active
  panier: {}, // produit_id → {qte, ...}
  payMode: null,
  pcUrl: '',       // URL serveur PC SelfFarm (ex: http://192.168.1.10:8003)
  pcStatus: 'unknown' // 'unknown' | 'connected' | 'disconnected' | 'not_configured'
};

// ============ UI helpers ============
function toast(msg, type = 'info', delay = 2500) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + (type === 'warn' ? 'warn' : type === 'error' ? 'error' : '') + ' show';
  setTimeout(() => t.classList.remove('show'), delay);
}

function fmtEur(n) { return Number(n || 0).toLocaleString('fr-FR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' €'; }
function escapeHtml(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function setScreen(name) {
  app.currentScreen = name;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.screen === name));
  const renderers = {caisse: renderCaisse, catalogue: renderCatalogue, sessions: renderSessions, coffre: renderCoffre, settings: renderSettings};
  if (renderers[name]) renderers[name]();
  // Cache panier flottant si pas sur caisse
  document.getElementById('panier').classList.toggle('show', name === 'caisse' && Object.keys(app.panier).length > 0);
}

document.querySelectorAll('.tab-btn').forEach(b => b.addEventListener('click', () => setScreen(b.dataset.screen)));

// ============ Online indicator ============
function updateNet() {
  const txt = document.getElementById('netText');
  if (navigator.onLine) txt.textContent = 'En ligne';
  else txt.textContent = 'Hors ligne';
  // Online change → recheck PC
  checkPCConnection();
}
window.addEventListener('online', updateNet);
window.addEventListener('offline', updateNet);

// ============ PC SelfFarm connection check ============
async function checkPCConnection() {
  const dot = document.getElementById('pcDot');
  const label = document.getElementById('pcLabel');
  if (!app.pcUrl || !app.pcUrl.trim()) {
    app.pcStatus = 'not_configured';
    dot.style.background = '#666';
    label.textContent = 'PC ?';
    return;
  }
  if (!navigator.onLine) {
    app.pcStatus = 'disconnected';
    dot.style.background = '#d4a056';
    label.textContent = 'PC ⚠';
    return;
  }
  try {
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 3000);
    const r = await fetch(app.pcUrl.replace(/\/$/, '') + '/api/pos/health', {
      signal: controller.signal,
      mode: 'cors',
      cache: 'no-store'
    });
    if (r.ok) {
      const data = await r.json();
      if (data.ok) {
        app.pcStatus = 'connected';
        dot.style.background = '#4a7c5e';
        label.textContent = 'PC ✓';
        return;
      }
    }
    app.pcStatus = 'disconnected';
    dot.style.background = '#b85751';
    label.textContent = 'PC ✗';
  } catch (err) {
    app.pcStatus = 'disconnected';
    dot.style.background = '#b85751';
    label.textContent = 'PC ✗';
  }
}

document.getElementById('pcStatusBtn').addEventListener('click', () => {
  // Toast feedback puis check
  toast('Vérification connexion PC…', 'info', 1500);
  checkPCConnection().then(() => {
    if (app.pcStatus === 'connected') toast('✓ PC SelfFarm joignable', 'info');
    else if (app.pcStatus === 'not_configured') toast('Configure l\'URL du PC dans Réglages', 'warn', 3000);
    else toast('PC injoignable — vérifie WiFi/hotspot', 'error', 3000);
  });
});

// Polling auto toutes les 10s
setInterval(checkPCConnection, 10000);

// ============ Screen: Caisse ============
async function renderCaisse() {
  document.getElementById('screenTitle').textContent = app.currentSession
    ? `Marché ${app.currentSession.lieu}`
    : 'SelfPOS';

  const content = document.getElementById('content');
  if (!app.catalogue || app.catalogue.length === 0) {
    content.innerHTML = `
      <div class="empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
        <p>Catalogue vide.</p>
        <p>Va sur <strong>Réglages</strong> pour importer ton catalogue depuis SelfFarm.</p>
      </div>`;
    return;
  }

  if (!app.currentSession) {
    content.innerHTML = `
      <div class="card">
        <h2>Nouveau marché</h2>
        <p>Avant d'encaisser, prépare ton chargement.</p>
        <div class="field">
          <label>Date</label>
          <input type="date" id="newSessDate" value="${new Date().toISOString().slice(0,10)}">
        </div>
        <div class="field">
          <label>Lieu</label>
          <input type="text" id="newSessLieu" placeholder="ex : Marché de Sainte-Foy">
        </div>
        <button class="btn" data-action="start-session">Démarrer le marché →</button>
      </div>`;
    return;
  }

  // Session active → grille produits chargés + visibles
  const charges = await dbGetAll('chargement');
  const sessionCharges = charges.filter(c => c.session_local_id === app.currentSession.local_id);
  const chargesMap = new Map(sessionCharges.map(c => [c.produit_id, c]));

  const produitsAffiches = app.catalogue
    .filter(p => app.visibility[p.id] !== false)
    .filter(p => chargesMap.has(p.id));

  if (produitsAffiches.length === 0) {
    content.innerHTML = `
      <div class="card">
        <h2>Préparer le chargement</h2>
        <p>Sélectionne les produits que tu emportes pour ce marché.</p>
        <button class="btn" data-action="screen" data-screen="catalogue">Aller au catalogue →</button>
      </div>`;
    return;
  }

  // Calcul stock restant par produit (chargé - vendu en cette session)
  const ventes = (await dbGetAll('ventes')).filter(v => v.session_local_id === app.currentSession.local_id);
  const venduParProduit = {};
  ventes.forEach(v => (v.lignes || []).forEach(l => {
    venduParProduit[l.produit_id] = (venduParProduit[l.produit_id] || 0) + Number(l.qte || 0);
  }));

  content.innerHTML = `
    <div style="margin-bottom:10px; padding:10px 14px; background:var(--bg-elev); border-radius:8px; font-size:12px; color:var(--text-secondary); display:flex; justify-content:space-between;">
      <span>${ventes.length} vente${ventes.length>1?'s':''}</span>
      <span style="color:var(--accent-200); font-weight:600;">${fmtEur(ventes.reduce((s, v) => s + Number(v.total_ttc || 0), 0))}</span>
      <a href="#" data-action="fin-marche" style="color:var(--warm-amber);">Fin de marché →</a>
    </div>
    <div class="produits-grid" id="grid"></div>
  `;
  const grid = document.getElementById('grid');
  produitsAffiches.forEach(p => {
    const chg = chargesMap.get(p.id);
    const charged = chg.quantite_chargee;
    const vendu = venduParProduit[p.id] || 0;
    const reste = charged != null ? Math.max(0, charged - vendu) : null;
    const btn = document.createElement('button');
    btn.className = 'produit-btn';
    btn.innerHTML = `
      <div class="emoji">${p.emoji || '🌿'}</div>
      <div class="nom">${escapeHtml(p.nom)}</div>
      <div class="prix">${fmtEur(p.prix_unitaire)}</div>
      ${reste !== null ? `<div class="stock-info">${reste.toFixed(1)} / ${charged} ${escapeHtml(p.unite)}</div>` : `<div class="stock-info">/ ${escapeHtml(p.unite)}</div>`}
    `;
    btn.addEventListener('click', () => addToPanier(p));
    grid.appendChild(btn);
  });
  renderPanier();
}

// Unités au POIDS → pavé numérique intégré (balance, précision 0,001). Autres → +1.
const UNITES_POIDS = ['kg', 'g', 'kilo', 'kilos', 'gramme', 'grammes', 'l', 'litre', 'litres'];
function estAuPoids(unite) {
  return UNITES_POIDS.includes((unite || '').toLowerCase().trim());
}

// ── Pavé de pesée (modal in-app, comme sur une vraie caisse mobile) ──────────
let _peseeBuf = '';          // chiffres tapés (point décimal interne)
let _peseeOnValide = null;   // callback(poids) à la validation
let _peseePrix = 0, _peseeUnite = 'kg';

function ouvrirPesee(produit, valeurInit, onValide) {
  _peseeOnValide = onValide;
  _peseeBuf = (valeurInit != null && valeurInit > 0) ? String(valeurInit) : '';
  _peseePrix = produit.prix != null ? produit.prix : produit.prix_unitaire;
  _peseeUnite = produit.unite || 'kg';
  document.getElementById('peseeNom').textContent = `${produit.emoji || '🌿'} ${produit.nom || ''}`;
  peseeRender();
  document.getElementById('modalPesee').classList.add('open');
}
function peseeRender() {
  const disp = _peseeBuf === '' ? '0' : _peseeBuf.replace('.', ',');
  document.getElementById('peseeAff').textContent = `${disp} ${_peseeUnite}`;
  const v = parseFloat(_peseeBuf.replace(',', '.')) || 0;
  document.getElementById('peseeSous').textContent =
    (v * _peseePrix).toLocaleString('fr-FR', {style: 'currency', currency: 'EUR'});
}
function peseeKey(ch) {
  if (ch === ',') {
    if (_peseeBuf.includes('.')) return;
    _peseeBuf = (_peseeBuf === '' ? '0' : _peseeBuf) + '.';
  } else {
    const dec = _peseeBuf.split('.')[1];
    if (dec && dec.length >= 3) return;            // 3 décimales max (le gramme)
    if (_peseeBuf === '0') _peseeBuf = '';         // pas de zéro initial inutile
    _peseeBuf += ch;
  }
  peseeRender();
}
function peseeBackspace() { _peseeBuf = _peseeBuf.slice(0, -1); peseeRender(); }
function peseeAnnuler() {
  document.getElementById('modalPesee').classList.remove('open');
  _peseeOnValide = null;
}
function peseeValider() {
  const v = Math.round((parseFloat(_peseeBuf.replace(',', '.')) || 0) * 1000) / 1000;
  const cb = _peseeOnValide;
  peseeAnnuler();
  if (cb) cb(v);
}

function editPoids(produitId) {
  const l = app.panier[produitId];
  if (!l) return;
  ouvrirPesee(l, l.qte, (v) => {              // edit = remplace le poids total
    if (v <= 0) delete app.panier[produitId]; else l.qte = v;
    renderPanier();
  });
}

function addToPanier(p) {
  if (estAuPoids(p.unite)) {
    ouvrirPesee(p, null, (v) => {             // ajout = cumule la pesée
      if (v <= 0) return;
      if (!app.panier[p.id]) {
        app.panier[p.id] = {id: p.id, nom: p.nom, prix: p.prix_unitaire, unite: p.unite, emoji: p.emoji, qte: 0};
      }
      app.panier[p.id].qte = Math.round((app.panier[p.id].qte + v) * 1000) / 1000;
      if (app.panier[p.id].qte <= 0) delete app.panier[p.id];
      renderPanier();
    });
  } else {
    if (!app.panier[p.id]) {
      app.panier[p.id] = {id: p.id, nom: p.nom, prix: p.prix_unitaire, unite: p.unite, emoji: p.emoji, qte: 0};
    }
    app.panier[p.id].qte += 1;
    renderPanier();
  }
}

function changerQte(produitId, delta) {
  if (!app.panier[produitId]) return;
  app.panier[produitId].qte += delta;
  if (app.panier[produitId].qte <= 0) delete app.panier[produitId];
  renderPanier();
}

function totalPanier() {
  return Object.values(app.panier).reduce((s, l) => s + l.prix * l.qte, 0);
}

function qtyCtrlHtml(l) {
  if (estAuPoids(l.unite)) {
    const poids = l.qte.toLocaleString('fr-FR', {minimumFractionDigits: 3, maximumFractionDigits: 3});
    return `<button data-action="edit-poids" data-id="${l.id}" title="Modifier le poids" style="background:transparent;border:1px dashed var(--accent-500);color:var(--text-primary);padding:4px 9px;border-radius:5px;font-size:12px;white-space:nowrap;">${poids} ${escapeHtml(l.unite)} ✎</button>`;
  }
  return `<button data-action="qte" data-id="${l.id}" data-delta="-1">−</button><span class="qty-val">${l.qte}</span><button data-action="qte" data-id="${l.id}" data-delta="1">+</button>`;
}

function renderPanier() {
  const div = document.getElementById('panier');
  const lignes = Object.values(app.panier);
  if (lignes.length === 0) { div.classList.remove('show'); div.innerHTML = ''; return; }
  div.classList.add('show');
  div.innerHTML = `
    ${lignes.map(l => `
      <div class="panier-row">
        <span class="emo">${l.emoji || '🌿'}</span>
        <div class="info">
          <div class="nom-l">${escapeHtml(l.nom)}</div>
          <div class="meta-l">${fmtEur(l.prix)} / ${escapeHtml(l.unite)}</div>
        </div>
        <div class="qty-ctrl">${qtyCtrlHtml(l)}</div>
        <div class="total-l">${fmtEur(l.prix * l.qte)}</div>
      </div>`).join('')}
    <div class="panier-bar">
      <div class="total">${fmtEur(totalPanier())}</div>
      <button class="btn btn-encaisser" data-action="open-pay">Encaisser</button>
    </div>
  `;
}

function openModalPay() {
  if (Object.keys(app.panier).length === 0) return;
  app.payMode = null;
  document.getElementById('modalPayTotal').textContent = fmtEur(totalPanier());
  document.querySelectorAll('.payment-grid .opt').forEach(o => o.classList.remove('selected'));
  document.getElementById('btnConfirmPay').disabled = true;
  document.getElementById('modalPay').classList.add('open');
}
function closeModalPay() { document.getElementById('modalPay').classList.remove('open'); }
function selectPay(mode) {
  app.payMode = mode;
  document.querySelectorAll('.payment-grid .opt').forEach(o => o.classList.toggle('selected', o.dataset.mode === mode));
  document.getElementById('btnConfirmPay').disabled = false;
}

async function confirmPay() {
  if (!app.payMode || Object.keys(app.panier).length === 0) return;
  const total = totalPanier();
  const lignes = Object.values(app.panier).map(l => ({
    produit_id: l.id, nom: l.nom, emoji: l.emoji, prix: l.prix, unite: l.unite, qte: l.qte, total: l.prix * l.qte
  }));
  const uuid = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : ('mob-' + Date.now() + '-' + Math.random().toString(36).slice(2));
  const vente = {
    offline_uuid: uuid,
    session_local_id: app.currentSession.local_id,
    lignes, total_ttc: total,
    mode_paiement: app.payMode,
    created_at: new Date().toISOString()
  };
  await dbPut('ventes', vente);
  closeModalPay();
  app.panier = {};
  toast(`✓ Vente ${fmtEur(total)} enregistrée`, 'info');
  renderCaisse();
}

// ============ Démarrer un marché ============
async function startNewSession() {
  const date = document.getElementById('newSessDate').value;
  const lieu = document.getElementById('newSessLieu').value.trim();
  if (!date || !lieu) { toast('Date et lieu requis', 'warn'); return; }
  // Cherche la prochaine local_id
  const sessions = await dbGetAll('sessions');
  const session = {
    date_marche: date, lieu,
    statut: 'ouverte',
    started_at: new Date().toISOString()
  };
  const newId = await dbPut('sessions', session);
  session.local_id = newId;
  app.currentSession = session;
  await dbPut('settings', {key: 'current_session_local_id', value: newId});
  toast(`Marché ${lieu} démarré`, 'info');
  renderCaisse();
}

// ============ Screen: Catalogue ============
async function renderCatalogue() {
  document.getElementById('screenTitle').textContent = 'Catalogue';
  document.getElementById('panier').classList.remove('show');
  const content = document.getElementById('content');

  if (!app.catalogue || app.catalogue.length === 0) {
    content.innerHTML = `
      <div class="empty">
        <p>Aucun catalogue importé.</p>
        <button class="btn" style="margin-top:14px;" data-action="screen" data-screen="settings">Importer depuis SelfFarm →</button>
      </div>`;
    return;
  }

  let html = '';

  if (app.currentSession) {
    const charges = (await dbGetAll('chargement')).filter(c => c.session_local_id === app.currentSession.local_id);
    const chargesMap = new Map(charges.map(c => [c.produit_id, c]));
    html += `<div class="card">
      <h2>📦 Chargement — ${escapeHtml(app.currentSession.lieu)}</h2>
      <p>Coche les produits pour ce marché. La quantité est <strong>optionnelle</strong>.</p>`;
    for (const p of app.catalogue.filter(p => app.visibility[p.id] !== false || chargesMap.has(p.id))) {
      const chg = chargesMap.get(p.id);
      const checked = !!chg;
      html += `
        <div class="toggle-row">
          <span class="emo">${p.emoji || '🌿'}</span>
          <div class="info">
            <div class="nom">${escapeHtml(p.nom)}</div>
            <div class="meta">${fmtEur(p.prix_unitaire)} / ${escapeHtml(p.unite)}</div>
            <input type="number" step="0.1" min="0" placeholder="qté (optionnel)" value="${chg?.quantite_chargee ?? ''}" id="qte_${p.id}" style="width:120px; margin-top:5px; padding:5px 8px; background:#0a1410; border:1px solid var(--border-default); color:var(--text-primary); border-radius:5px; font-size:12px;" data-change="chargement-qte" data-id="${p.id}">
            <span style="font-size:11px; color:var(--text-muted); margin-left:4px;">${escapeHtml(p.unite)}</span>
          </div>
          <label class="switch">
            <input type="checkbox" ${checked ? 'checked' : ''} data-change="chargement-toggle" data-id="${p.id}">
            <span></span>
          </label>
        </div>`;
    }
    html += `</div>`;
  } else {
    html += `<div class="card">
      <p style="text-align:center; color:var(--text-secondary);">Démarre un marché depuis l'onglet <strong>Caisse</strong> pour préparer le chargement.</p>
    </div>`;
  }

  // Visibilité globale produits (toujours dispo)
  html += `<div class="card">
    <h2>👁 Visibilité globale</h2>
    <p>Masque des produits que tu ne vends jamais (juste sur ce mobile, pas côté SelfFarm).</p>`;
  for (const p of app.catalogue) {
    const visible = app.visibility[p.id] !== false;
    html += `
      <div class="toggle-row">
        <span class="emo">${p.emoji || '🌿'}</span>
        <div class="info">
          <div class="nom">${escapeHtml(p.nom)}</div>
          <div class="meta">${fmtEur(p.prix_unitaire)} / ${escapeHtml(p.unite)}</div>
        </div>
        <label class="switch">
          <input type="checkbox" ${visible ? 'checked' : ''} data-change="visibility" data-id="${p.id}">
          <span></span>
        </label>
      </div>`;
  }
  html += `</div>`;

  content.innerHTML = html;
}

async function toggleVisibility(produitId, visible) {
  app.visibility[produitId] = visible;
  await dbPut('settings', {key: 'visibility', value: app.visibility});
}

async function toggleChargement(produitId, checked) {
  const p = app.catalogue.find(x => x.id === produitId);
  if (!p || !app.currentSession) return;
  if (checked) {
    await dbPut('chargement', {
      session_local_id: app.currentSession.local_id,
      produit_id: produitId, produit_nom: p.nom, unite: p.unite,
      quantite_chargee: null
    });
  } else {
    await dbDelete('chargement', [app.currentSession.local_id, produitId]);
  }
}

async function updateChargementQte(produitId) {
  if (!app.currentSession) return;
  const val = document.getElementById(`qte_${produitId}`).value;
  const qte = val.trim() ? parseFloat(val) : null;
  const existing = await dbGet('chargement', [app.currentSession.local_id, produitId]);
  if (!existing) return; // pas coché, ignore
  existing.quantite_chargee = qte;
  await dbPut('chargement', existing);
}

// ============ Screen: Sessions (historique) ============
async function renderSessions() {
  document.getElementById('screenTitle').textContent = 'Mes marchés';
  document.getElementById('panier').classList.remove('show');
  const content = document.getElementById('content');
  const sessions = (await dbGetAll('sessions')).sort((a, b) => (b.local_id || 0) - (a.local_id || 0));
  if (sessions.length === 0) {
    content.innerHTML = `<div class="empty"><p>Aucune session encore.</p></div>`;
    return;
  }
  const ventes = await dbGetAll('ventes');
  let html = '';
  for (const s of sessions) {
    const sVentes = ventes.filter(v => v.session_local_id === s.local_id);
    const total = sVentes.reduce((sum, v) => sum + Number(v.total_ttc || 0), 0);
    html += `
      <div class="session-card">
        <div class="head">
          <span class="lieu">${escapeHtml(s.lieu)}</span>
          <span class="total">${fmtEur(total)}</span>
        </div>
        <div class="meta">${s.date_marche} · ${sVentes.length} vente${sVentes.length>1?'s':''} · ${escapeHtml(s.statut)}</div>
        ${s.statut === 'ouverte' ? `
          <button class="btn" style="margin-top:10px;" data-action="reprendre-session" data-id="${s.local_id}">Reprendre</button>
          <button class="btn btn-warn" style="margin-top:6px;" data-action="fin-marche-session" data-id="${s.local_id}">Fin de marché</button>
        ` : `
          <button class="btn btn-ghost" style="margin-top:10px;" data-action="export-session" data-id="${s.local_id}">⬇ Re-télécharger fichier</button>
        `}
      </div>`;
  }
  content.innerHTML = html;
}

async function reprendreSession(localId) {
  const s = await dbGet('sessions', localId);
  if (!s || s.statut !== 'ouverte') return;
  app.currentSession = s;
  await dbPut('settings', {key: 'current_session_local_id', value: localId});
  setScreen('caisse');
}

// ============ Fin de marché ============
async function finMarche() {
  if (!app.currentSession) return;
  finMarcheSession(app.currentSession.local_id);
}

async function finMarcheSession(localId) {
  const s = await dbGet('sessions', localId);
  if (!s) return;
  const charges = (await dbGetAll('chargement')).filter(c => c.session_local_id === localId);
  const ventes = (await dbGetAll('ventes')).filter(v => v.session_local_id === localId);
  // Calcule vendu par produit
  const venduMap = {};
  ventes.forEach(v => (v.lignes || []).forEach(l => {
    venduMap[l.produit_id] = (venduMap[l.produit_id] || 0) + Number(l.qte || 0);
  }));

  const content = document.getElementById('content');
  document.getElementById('screenTitle').textContent = `Fin — ${s.lieu}`;
  document.getElementById('panier').classList.remove('show');

  const totalSession = ventes.reduce((sum, v) => sum + Number(v.total_ttc || 0), 0);

  let html = `
    <div class="card">
      <h2>🎉 ${escapeHtml(s.lieu)}</h2>
      <p>${s.date_marche} · ${ventes.length} ventes · <strong style="color:var(--accent-200);">${fmtEur(totalSession)}</strong></p>
    </div>

    <div class="card">
      <h2>📦 Résidus à classer</h2>
      <p>Pour chaque produit chargé, choisis ce que tu fais du reste.</p>
      <div class="residus-table">`;

  if (charges.length === 0) {
    html += `<p style="text-align:center; padding:20px; color:var(--text-muted);">Aucun produit chargé. Tu peux exporter directement.</p>`;
  } else {
    for (const c of charges) {
      const vendu = venduMap[c.produit_id] || 0;
      const reste = c.quantite_chargee != null ? Math.max(0, c.quantite_chargee - vendu) : null;
      html += `
        <div class="row" data-produit="${c.produit_id}">
          <div class="info-prod">
            <div class="nom-r">${escapeHtml(c.produit_nom)}</div>
            <div class="meta-r">${c.quantite_chargee != null ? `Chargé ${c.quantite_chargee} · Vendu ${vendu.toFixed(1)}` : `Vendu ${vendu.toFixed(1)}`}</div>
          </div>
          <input type="number" step="0.1" min="0" placeholder="reste"
                 value="${reste !== null ? reste : ''}"
                 id="reste_${c.produit_id}">
          <select id="status_${c.produit_id}">
            <option value="">— action —</option>
            <option value="invendu_poules">Invendu → poules</option>
            <option value="invendu_compost">Invendu → compost</option>
            <option value="invendu_don">Invendu → don</option>
            <option value="invendu_garde_maison">Invendu → garde maison</option>
            <option value="invendu_poubelle">Invendu → poubelle</option>
            <option value="stock">Stock prochain marché</option>
            <option value="consomme_hors_marche">Vendu hors marché (AMAP…)</option>
          </select>
        </div>`;
    }
  }
  html += `</div></div>

    <button class="btn" data-action="export-fichier" data-id="${localId}">⬇ Exporter le fichier marché</button>
    <button class="btn btn-ghost" style="margin-top:8px;" data-action="screen" data-screen="sessions">Annuler</button>
  `;
  content.innerHTML = html;
}

async function exportFichierMarche(localId) {
  const s = await dbGet('sessions', localId);
  if (!s) return;
  const charges = (await dbGetAll('chargement')).filter(c => c.session_local_id === localId);
  const ventes = (await dbGetAll('ventes')).filter(v => v.session_local_id === localId);

  // Collecte résidus depuis le formulaire
  const residus = [];
  for (const c of charges) {
    const resteInput = document.getElementById(`reste_${c.produit_id}`);
    const statusSelect = document.getElementById(`status_${c.produit_id}`);
    if (!resteInput || !statusSelect) continue;
    const reste = parseFloat(resteInput.value);
    const statusVal = statusSelect.value;
    if (!statusVal || !reste || reste <= 0) continue;
    let status, destination = null;
    if (statusVal.startsWith('invendu_')) { status = 'invendu'; destination = statusVal.replace('invendu_', ''); }
    else if (statusVal === 'stock') status = 'stock';
    else if (statusVal === 'consomme_hors_marche') status = 'consomme_hors_marche';
    residus.push({
      produit_id: c.produit_id, produit_nom: c.produit_nom, unite: c.unite,
      quantite: reste, status, destination
    });
  }

  const exportData = {
    format: 'selffarm-pos-marche',
    version: '0.3.0',
    device_uuid: await getOrCreateDeviceUUID(),
    exported_at: new Date().toISOString(),
    session: {
      date_marche: s.date_marche, lieu: s.lieu,
      started_at: s.started_at, cloture_at: new Date().toISOString(), notes: s.notes || ''
    },
    chargement: charges.map(c => ({
      produit_id: c.produit_id, produit_nom: c.produit_nom,
      unite: c.unite, quantite_chargee: c.quantite_chargee
    })),
    ventes: ventes.map(v => ({
      offline_uuid: v.offline_uuid, lignes: v.lignes,
      total_ttc: v.total_ttc, mode_paiement: v.mode_paiement,
      client_libelle: v.client_libelle, created_at: v.created_at
    })),
    residus
  };
  // Checksum SHA-256
  const enc = new TextEncoder();
  const buf = enc.encode(JSON.stringify(exportData));
  const hashBuf = await crypto.subtle.digest('SHA-256', buf);
  exportData.checksum_sha256 = Array.from(new Uint8Array(hashBuf)).map(b => b.toString(16).padStart(2, '0')).join('');

  // Marquer session clôturée localement
  s.statut = 'cloturee';
  s.cloture_at = new Date().toISOString();
  await dbPut('sessions', s);
  if (app.currentSession && app.currentSession.local_id === localId) {
    app.currentSession = null;
    await dbDelete('settings', 'current_session_local_id');
  }

  // Download du JSON
  const filename = `marche-${s.date_marche}-${(s.lieu || 'marche').toLowerCase().replace(/[^a-z0-9]/g, '-')}.json`;
  const blob = new Blob([JSON.stringify(exportData, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
  toast('✓ Fichier marché exporté. Transfère-le sur ton PC SelfFarm.', 'info', 4000);
  setScreen('sessions');
}

async function exportSession(localId) {
  // Re-export sans recalcul résidus (déjà clôturé)
  const s = await dbGet('sessions', localId);
  const charges = (await dbGetAll('chargement')).filter(c => c.session_local_id === localId);
  const ventes = (await dbGetAll('ventes')).filter(v => v.session_local_id === localId);
  const exportData = {
    format: 'selffarm-pos-marche', version: '0.3.0',
    device_uuid: await getOrCreateDeviceUUID(),
    exported_at: new Date().toISOString(),
    session: {date_marche: s.date_marche, lieu: s.lieu, started_at: s.started_at, cloture_at: s.cloture_at, notes: s.notes || ''},
    chargement: charges.map(c => ({produit_id: c.produit_id, produit_nom: c.produit_nom, unite: c.unite, quantite_chargee: c.quantite_chargee})),
    ventes: ventes.map(v => ({offline_uuid: v.offline_uuid, lignes: v.lignes, total_ttc: v.total_ttc, mode_paiement: v.mode_paiement, created_at: v.created_at})),
    residus: []
  };
  const blob = new Blob([JSON.stringify(exportData, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = `marche-${s.date_marche}-${(s.lieu || 'marche').toLowerCase().replace(/[^a-z0-9]/g, '-')}.json`;
  a.click();
  URL.revokeObjectURL(url);
  toast('Fichier re-téléchargé', 'info');
}

async function getOrCreateDeviceUUID() {
  let stored = await dbGet('settings', 'device_uuid');
  if (stored) return stored.value;
  const uuid = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : ('dev-' + Date.now() + '-' + Math.random().toString(36).slice(2));
  await dbPut('settings', {key: 'device_uuid', value: uuid});
  return uuid;
}

// ============ Screen: Settings ============
// ============ Coffre de sauvegarde (Lot D / E) ============
async function syncBackup(manual) {
  const vault = await dbGet('settings', 'vault');
  if (!vault || !vault.value) { if (manual) toast('Coffre non appairé', 'warn'); return; }
  const base = app.pcUrl || location.origin;
  try {
    const m = await fetch(base + '/api/pos/backup/manifest').then(r => r.json());
    if (!m.available) { if (manual) toast('Rien à sauvegarder côté PC', 'warn'); return; }
    // Le PC a changé de clé depuis l'appairage : ce téléphone ne saurait pas
    // rendre une sauvegarde chiffrée avec la nouvelle.
    if (m.vault_key_id && vault.value.vault_key_id && m.vault_key_id !== vault.value.vault_key_id) {
      toast('La clé du coffre du PC a changé : ré-appaire ce téléphone (Sauvegardes → Appairer un coffre mobile).', 'warn', 6000);
      return;
    }
    if (await dbGet('backups', m.sha256)) { if (manual) toast('Déjà à jour ✓', 'info'); return; }
    const resp = await fetch(base + '/api/pos/backup/download');
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const buf = await resp.arrayBuffer();
    const name = resp.headers.get('X-Backup-Name') || 'selffarm-backup.zip.vault';
    const sha = resp.headers.get('X-Backup-Sha') || m.sha256;
    // Chaque sauvegarde garde sa clé : un ré-appairage ne la rend pas illisible.
    await dbPut('backups', {sha, name, date: new Date().toISOString(), size: buf.byteLength, blob: buf,
                            vault_key: vault.value.vault_key});
    const all = (await dbGetAll('backups')).sort((a, b) => a.date < b.date ? 1 : -1);
    for (const old of all.slice(30)) await dbDelete('backups', old.sha); // rétention 30
    toast('🔐 Sauvegarde déposée sur le coffre', 'info', 2500);
    if (app.currentScreen === 'coffre') renderCoffre();
  } catch (e) { if (manual) toast('Sauvegarde échouée : ' + e.message, 'error'); }
}

// Le fichier porte la sauvegarde ET sa clé : le PC qui le reçoit n'a besoin de rien
// d'autre, même neuf. Il vaut donc une sauvegarde en clair.
async function exportBackup(sha) {
  const b = await dbGet('backups', sha);
  if (!b) { toast('Sauvegarde introuvable', 'error'); return; }
  const vault = await dbGet('settings', 'vault');
  const cle = b.vault_key || (vault && vault.value && vault.value.vault_key);
  if (!cle) { toast('Clé du coffre introuvable sur ce téléphone', 'error'); return; }
  const fichier = {format: 'selffarm-coffre', version: 1, backup_name: b.name, vault_key: cle,
                   token: new TextDecoder().decode(b.blob)};
  // octet-stream : en application/json, Android ajouterait « .json » au nom.
  const blob = new Blob([JSON.stringify(fichier)], {type: 'application/octet-stream'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = b.name.replace(/\.zip\.vault$/, '') + '.sfcoffre';
  a.click();
  URL.revokeObjectURL(url);
  toast('✓ Fichier exporté. Sur le PC : Sauvegarde → Restaurer, puis supprime-le de ce téléphone.', 'info', 6000);
}

async function renderCoffre() {
  document.getElementById('screenTitle').textContent = 'Coffre';
  document.getElementById('panier').classList.remove('show');
  const content = document.getElementById('content');
  const vault = await dbGet('settings', 'vault');
  if (!vault || !vault.value) {
    content.innerHTML = `<div class="card"><h2>🔐 Coffre de sauvegarde</h2>
      <p>Ce téléphone n'est pas encore appairé. Sur le PC : <strong>Sauvegardes → Appairer un coffre mobile</strong>, puis scanne le QR affiché.</p></div>`;
    return;
  }
  const backups = (await dbGetAll('backups')).sort((a, b) => a.date < b.date ? 1 : -1);
  content.innerHTML = `
    <div class="card">
      <h2>🔐 Coffre de sauvegarde</h2>
      <p>Ce téléphone garde <strong>${backups.length}</strong> sauvegarde(s) chiffrée(s) de ton SelfFarm, avec la clé qui les ouvre.</p>
      <p>Pour en rendre une à un PC, même neuf : <strong>Exporter</strong>, puis sur le PC <strong>Sauvegarde → Restaurer</strong> avec ce fichier. Ça marche même si le PC n'a plus la même adresse.</p>
      <p style="color:var(--text-muted); font-size:12px;">⚠ Le fichier exporté contient la clé : garde-le hors du cloud du téléphone, et supprime-le une fois importé.</p>
      <button class="btn" data-action="sync-backup">⟳ Sauvegarder maintenant</button>
    </div>
    ${backups.length === 0 ? '<div class="card"><p style="color:var(--text-muted);">Aucune sauvegarde encore. Connecte-toi au PC puis touche « Sauvegarder maintenant ».</p></div>' : ''}
    ${backups.map(b => `
      <div class="card" style="padding:12px 14px;">
        <div style="font-size:11.5px; font-family:monospace; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(b.name)}</div>
        <div style="font-size:11px; color:var(--text-muted); margin-top:3px;">${new Date(b.date).toLocaleString('fr-FR')} · ${(b.size / 1024).toFixed(1)} Ko</div>
        <button class="btn btn-ghost" style="margin-top:8px; font-size:12px;" data-action="export-backup" data-sha="${b.sha}">↓ Exporter ce fichier</button>
      </div>`).join('')}
  `;
}

function renderSettings() {
  document.getElementById('screenTitle').textContent = 'Réglages';
  document.getElementById('panier').classList.remove('show');
  const content = document.getElementById('content');
  content.innerHTML = `
    <div class="card">
      <h2>🖥 Connexion PC SelfFarm</h2>
      <p>URL du PC sur ton réseau local. Le voyant en haut devient vert quand le PC répond.</p>
      <div class="field">
        <label>URL PC (ex: http://192.168.1.10:8003)</label>
        <input type="url" id="pcUrlInput" placeholder="http://..." value="${escapeHtml(app.pcUrl)}">
      </div>
      <button class="btn" data-action="save-pc-url">Enregistrer + tester</button>
      <button class="btn btn-ghost" style="margin-top:6px;" data-action="test-pc">Re-tester</button>
    </div>

    <div class="card">
      <h2>📥 Importer catalogue</h2>
      <p>Fichier <strong>selffarm-catalogue.json</strong> exporté depuis ton SelfFarm Windows.</p>
      <input type="file" accept=".json,application/json" id="fileCatalog" style="display:none;" data-change="catalog-import">
      <button class="btn" data-action="pick-catalog">Choisir un fichier</button>
    </div>

    <div class="card">
      <h2>📊 Statistiques locales</h2>
      <div id="statsBox" style="font-size:13px; color:var(--text-secondary); line-height:1.8;"></div>
    </div>

    <div class="card">
      <h2>⚠ Reset</h2>
      <p>Supprime <strong>toutes les données locales</strong> (catalogue, sessions, ventes, paramètres). Action irréversible — à faire seulement si tu as exporté tous tes fichiers marchés.</p>
      <button class="btn btn-warn" data-action="reset-all">Tout effacer</button>
    </div>

    <div style="text-align:center; padding:20px; color:var(--text-muted); font-size:11px;">
      SelfPOS Mobile · PWA AGPL-3.0 · v${APP_VERSION}
    </div>
  `;
  renderStats();
}

async function renderStats() {
  const sessions = await dbGetAll('sessions');
  const ventes = await dbGetAll('ventes');
  const totalTtc = ventes.reduce((s, v) => s + Number(v.total_ttc || 0), 0);
  document.getElementById('statsBox').innerHTML = `
    <div>Catalogue : <strong>${app.catalogue.length}</strong> produits</div>
    <div>Sessions : <strong>${sessions.length}</strong></div>
    <div>Ventes totales : <strong>${ventes.length}</strong></div>
    <div>Cumul TTC : <strong style="color:var(--accent-200);">${fmtEur(totalTtc)}</strong></div>
  `;
}

async function savePCUrl() {
  const v = document.getElementById('pcUrlInput').value.trim();
  app.pcUrl = v;
  await dbPut('settings', {key: 'pc_url', value: v});
  toast('URL PC enregistrée — test en cours…', 'info', 1500);
  await checkPCConnection();
  if (app.pcStatus === 'connected') toast('✓ PC SelfFarm joignable', 'info');
  else if (app.pcStatus !== 'not_configured') toast('PC injoignable — vérifie WiFi/URL', 'error', 3000);
}

async function handleCatalogImport(input) {
  const file = input.files[0];
  if (!file) return;
  try {
    const text = await file.text();
    const data = JSON.parse(text);
    if (data.format !== 'selffarm-pos-catalogue') {
      toast('Format invalide (selffarm-pos-catalogue attendu)', 'error', 4000);
      return;
    }
    await dbClear('catalogue');
    for (const p of data.produits) {
      await dbPut('catalogue', p);
    }
    app.catalogue = data.produits;
    toast(`✓ ${data.produits.length} produits importés`, 'info');
    renderStats();
  } catch (e) {
    toast('Erreur lecture fichier : ' + e.message, 'error', 4000);
  }
}

async function resetAll() {
  if (!confirm('Tout effacer ? Toutes les données locales seront perdues.')) return;
  for (const s of STORES) await dbClear(s);
  app.catalogue = [];
  app.visibility = {};
  app.currentSession = null;
  app.panier = {};
  toast('Données effacées', 'warn');
  setScreen('caisse');
}

// ============ Boot ============
// ============ Appairage coffre de sauvegarde (Lot C) ============
async function tryPairing() {
  const token = new URLSearchParams(location.search).get('pair');
  if (!token) return;
  // Le service worker peut rouvrir la page sur son URL d'ouverture, jeton compris :
  // un jeton déjà consommé ici ne se rejoue pas (le PC le refuserait).
  const deja = await dbGet('settings', 'pair_token');
  if (deja && deja.value === token) { history.replaceState(null, '', location.pathname); return; }
  try {
    const base = app.pcUrl || location.origin;
    const r = await fetch(base + '/api/pos/pair', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({token, label: navigator.userAgent.includes('Android') ? 'Android' : 'Téléphone'})
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    await dbPut('settings', {key: 'vault', value: {
      device_id: data.device_id, vault_key: data.vault_key, vault_key_id: data.vault_key_id,
      server_url: data.server_url
    }});
    await dbPut('settings', {key: 'pair_token', value: token});
    if (data.server_url) {
      app.pcUrl = data.server_url;
      await dbPut('settings', {key: 'pc_url', value: app.pcUrl});
    }
    toast('🔐 Coffre de sauvegarde appairé', 'info', 3000);
  } catch (e) {
    toast('Appairage échoué : ' + e.message, 'error', 3500);
  } finally {
    history.replaceState(null, '', location.pathname); // jeton one-time → on nettoie l'URL
  }
}

(async function init() {
  await openDB();
  app.catalogue = await dbGetAll('catalogue');
  const vis = await dbGet('settings', 'visibility');
  app.visibility = vis ? vis.value : {};
  const csid = await dbGet('settings', 'current_session_local_id');
  if (csid) {
    const s = await dbGet('sessions', csid.value);
    if (s && s.statut === 'ouverte') app.currentSession = s;
  }

  // URL PC : charge depuis settings, ou auto-détecte l'origine actuelle si même-host
  const pcUrlStored = await dbGet('settings', 'pc_url');
  if (pcUrlStored && pcUrlStored.value) {
    app.pcUrl = pcUrlStored.value;
  } else if (location.origin && location.protocol.startsWith('http')) {
    // PWA chargée depuis le PC en LAN → même origin = même PC
    app.pcUrl = location.origin;
    await dbPut('settings', {key: 'pc_url', value: app.pcUrl});
  }

  // Appairage du coffre si le QR portait ?pair=<jeton>, puis dépôt auto best-effort
  await tryPairing();

  updateNet();
  setScreen('caisse');
  checkPCConnection();
  syncBackup(false); // dépôt auto si coffre appairé + nouveau backup dispo

  // Service worker
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/pos/sw-mobile.js', {scope: '/pos/mobile'}).catch(() => {});
  }
})();

SF.action('close-pay-overlay', (el, e) => { if (e.target === el) closeModalPay(); });
SF.action('select-pay', (el) => selectPay(el.dataset.mode));
SF.action('close-pay', () => closeModalPay());
SF.action('confirm-pay', () => confirmPay());
SF.action('pesee-overlay', (el, e) => { if (e.target === el) peseeAnnuler(); });
SF.action('pesee-key', (el) => peseeKey(el.dataset.key));
SF.action('pesee-backspace', () => peseeBackspace());
SF.action('pesee-annuler', () => peseeAnnuler());
SF.action('pesee-valider', () => peseeValider());
SF.action('start-session', () => startNewSession());
SF.action('screen', (el) => setScreen(el.dataset.screen));
SF.action('fin-marche', (el, e) => { e.preventDefault(); finMarche(); });
SF.action('edit-poids', (el) => editPoids(Number(el.dataset.id)));
SF.action('qte', (el) => changerQte(Number(el.dataset.id), Number(el.dataset.delta)));
SF.action('open-pay', () => openModalPay());
SF.action('chargement-qte', (el) => updateChargementQte(Number(el.dataset.id)));
SF.action('chargement-toggle', (el) => toggleChargement(Number(el.dataset.id), el.checked));
SF.action('visibility', (el) => toggleVisibility(Number(el.dataset.id), el.checked));
SF.action('reprendre-session', (el) => reprendreSession(Number(el.dataset.id)));
SF.action('fin-marche-session', (el) => finMarcheSession(Number(el.dataset.id)));
SF.action('export-session', (el) => exportSession(Number(el.dataset.id)));
SF.action('export-fichier', (el) => exportFichierMarche(Number(el.dataset.id)));
SF.action('sync-backup', () => syncBackup(true));
SF.action('export-backup', (el) => exportBackup(el.dataset.sha));
SF.action('save-pc-url', () => savePCUrl());
SF.action('test-pc', () => checkPCConnection().then(() => toast('Test connexion lancé', 'info', 1500)));
SF.action('catalog-import', (el) => handleCatalogImport(el));
SF.action('pick-catalog', () => document.getElementById('fileCatalog').click());
SF.action('reset-all', () => resetAll());
