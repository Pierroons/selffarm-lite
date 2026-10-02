const map = L.map('map', { zoomControl: true }).setView([46.6, 2.4], 6);
const mapEl = document.getElementById('map');
const statusEl = document.getElementById('status');

// Tuiles IGN
const ortho = L.tileLayer(
  'https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=ORTHOIMAGERY.ORTHOPHOTOS&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&STYLE=normal&TILEMATRIXSET=PM&FORMAT=image/jpeg',
  { attribution: '© IGN-F/Géoportail', maxZoom: 19, minZoom: 2 }
);
const planIGN = L.tileLayer(
  'https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&STYLE=normal&TILEMATRIXSET=PM&FORMAT=image/png',
  { attribution: '© IGN-F/Géoportail', maxZoom: 18, minZoom: 2 }
);
const cadastre = L.tileLayer(
  'https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=CADASTRALPARCELS.PARCELLAIRE_EXPRESS&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&STYLE=normal&TILEMATRIXSET=PM&FORMAT=image/png',
  { attribution: 'Cadastre IGN', maxZoom: 19, minZoom: 16, opacity: 0.75 }
);

ortho.addTo(map);
cadastre.addTo(map);

function setFond(type) {
  map.removeLayer(ortho);
  map.removeLayer(planIGN);
  map.removeLayer(cadastre);

  if (type === 'ortho') {
    ortho.addTo(map);
  } else if (type === 'plan') {
    planIGN.addTo(map);
  } else if (type === 'mix') {
    ortho.addTo(map);
    cadastre.addTo(map);
  }
  document.querySelectorAll('#btnFondOrtho, #btnFondPlan, #btnFondMix').forEach(b => b.classList.remove('active'));
  document.getElementById(type === 'ortho' ? 'btnFondOrtho' : type === 'plan' ? 'btnFondPlan' : 'btnFondMix').classList.add('active');
}

// Couche parcelles dynamiques
let parcelles = L.geoJSON(null, {
  style: { color: '#16a34a', weight: 2.5, fillColor: '#16a34a', fillOpacity: 0.3 },
  onEachFeature: (feat, layer) => {
    const p = feat.properties;
    const surface_ha = (p.contenance / 10000).toFixed(3);
    const payload = encodeURIComponent(JSON.stringify({
      nom: `${p.section}${p.numero}`,
      commune: p.nom_com || '',
      surface_ha: p.contenance / 10000,
      ref_cadastrale: p.idu || ''
    }));
    layer.bindPopup(`
      <b>Parcelle ${p.section}${p.numero}</b><br>
      IDU: <code>${p.idu}</code><br>
      Commune: ${p.nom_com} (${p.code_insee})<br>
      Surface: <b>${surface_ha} ha</b> (${p.contenance} m²)<br>
      Feuille: ${p.feuille}<br>
      <button data-action="ajouter-parcelle" data-payload="${payload}" style="margin-top:6px;padding:5px 10px;background:#16a34a;color:white;border:none;border-radius:4px;cursor:pointer;font-weight:600;">
        + Ajouter à mes parcelles
      </button>
    `);
  }
}).addTo(map);

// URL API IGN Cadastre (nécessite le paramètre source_ign=BDP depuis migration Géoplateforme)
const API_PARCELLE = 'https://apicarto.ign.fr/api/cadastre/parcelle';

async function ajouterAuxParcelles(payloadEncoded) {
  const data = JSON.parse(decodeURIComponent(payloadEncoded));
  const fd = new FormData();
  fd.append('nom', data.nom);
  fd.append('commune', data.commune);
  fd.append('surface_ha', data.surface_ha.toFixed(4));
  fd.append('statut', 'bio');
  fd.append('ref_cadastrale', data.ref_cadastrale);
  fd.append('notes', `Importée depuis carte IGN le ${new Date().toLocaleDateString('fr-FR')}`);
  try {
    statusEl.textContent = `⏳ Ajout parcelle ${data.nom} (${data.surface_ha.toFixed(3)} ha)…`;
    const r = await fetch('/parcelles/new', { method: 'POST', body: fd });
    if (r.ok || r.status === 303) {
      statusEl.textContent = `✓ Parcelle ${data.nom} ajoutée — ${data.surface_ha.toFixed(3)} ha`;
      // Notifie le parent (le wrapper iframe) qu'on vient d'ajouter une parcelle
      if (window.parent && window.parent !== window) {
        window.parent.postMessage({ type: 'parcelle-added', nom: data.nom, surface_ha: data.surface_ha }, window.location.origin);
      }
    } else {
      statusEl.textContent = `✗ Erreur ajout (HTTP ${r.status})`;
    }
  } catch (err) {
    statusEl.textContent = `✗ Erreur réseau : ${err.message}`;
  }
}

// Mode curseur
let mode = 'move';
function setMode(m) {
  mode = m;
  document.getElementById('btnModeMove').classList.toggle('active', m === 'move');
  document.getElementById('btnModeSelect').classList.toggle('active', m === 'select');
  if (m === 'select') {
    mapEl.classList.add('mode-select');
    statusEl.classList.add('selecting');
    statusEl.textContent = '🎯 Mode sélection — clique sur une parcelle pour la récupérer';
  } else {
    mapEl.classList.remove('mode-select');
    statusEl.classList.remove('selecting');
    statusEl.textContent = 'Mode : ✋ Déplacer — clique/glisse la carte avec la main';
  }
}

// Calcule surface approximative d'un polygone (en m²) via formule géodésique simplifiée
function surfacePolygone(coords) {
  // coords = [[lng, lat], ...] — polygone fermé ; approximation équirectangulaire
  if (!coords || coords.length < 3) return 0;
  const R = 6378137; // rayon Terre en m (EPSG:4326)
  const toRad = d => d * Math.PI / 180;
  let total = 0;
  for (let i = 0; i < coords.length; i++) {
    const [lng1, lat1] = coords[i];
    const [lng2, lat2] = coords[(i + 1) % coords.length];
    total += toRad(lng2 - lng1) * (2 + Math.sin(toRad(lat1)) + Math.sin(toRad(lat2)));
  }
  return Math.abs(total * R * R / 2);
}

// Enrichit les features avec la contenance calculée (l'API ne la fournit plus)
function enrichirFeatures(geo) {
  if (!geo.features) return geo;
  geo.features.forEach(f => {
    const props = f.properties || {};
    // IDU construit depuis code_insee + section + numero (padding 4 chiffres)
    if (!props.idu) {
      const num = String(props.numero || '').padStart(4, '0');
      props.idu = `${props.code_insee || ''}000${props.section || ''}${num}`;
    }
    // Contenance calculée depuis la géométrie si absente
    if (!props.contenance && f.geometry) {
      let coords = null;
      if (f.geometry.type === 'Polygon') coords = f.geometry.coordinates[0];
      else if (f.geometry.type === 'MultiPolygon') coords = f.geometry.coordinates[0][0];
      if (coords) props.contenance = Math.round(surfacePolygone(coords));
    }
    f.properties = props;
  });
  return geo;
}

// Clic sur la carte (mode select) — recherche parcelle à l'endroit cliqué
map.on('click', async (e) => {
  if (mode !== 'select') return;
  const { lat, lng } = e.latlng;
  statusEl.textContent = `⏳ Recherche parcelle à ${lat.toFixed(5)}, ${lng.toFixed(5)}…`;
  try {
    const geom = encodeURIComponent(JSON.stringify({
      type: 'Point', coordinates: [lng, lat]
    }));
    const url = `${API_PARCELLE}?geom=${geom}&_limit=1&source_ign=BDP`;
    const r = await fetch(url);
    const data = enrichirFeatures(await r.json());
    if (data.features && data.features.length > 0) {
      parcelles.addData(data);
      const p = data.features[0].properties;
      const ha = (p.contenance / 10000).toFixed(3);
      statusEl.textContent = `✓ Parcelle ${p.section}${p.numero} — ${ha} ha (commune ${p.nom_com})`;
      parcelles.getLayers().slice(-1)[0].openPopup();
    } else {
      statusEl.textContent = `✗ Aucune parcelle cadastrale à cet endroit`;
    }
  } catch (err) {
    statusEl.textContent = `✗ Erreur : ${err.message}`;
  }
});

async function chercherParcelle() {
  const commune = document.getElementById('commune').value.trim();
  const section = document.getElementById('section').value.trim();
  const numero = document.getElementById('numero').value.trim();
  const url = `${API_PARCELLE}?code_insee=${commune}&section=${section}&numero=${numero}&source_ign=BDP`;
  statusEl.textContent = `⏳ Recherche ${section}${numero}…`;
  try {
    const r = await fetch(url);
    const geo = enrichirFeatures(await r.json());
    parcelles.addData(geo);
    if (geo.features && geo.features.length > 0) {
      map.fitBounds(parcelles.getBounds(), { maxZoom: 18 });
      const p = geo.features[0].properties;
      const ha = (p.contenance / 10000).toFixed(3);
      statusEl.textContent = `✓ Parcelle ${p.section}${p.numero} — ${ha} ha (${p.nom_com})`;
    } else {
      statusEl.textContent = `✗ Aucune parcelle trouvée pour ${section}${numero} (${commune})`;
    }
  } catch (err) {
    statusEl.textContent = `✗ Erreur API : ${err.message}`;
  }
}

function effacerParcelles() {
  parcelles.clearLayers();
  statusEl.textContent = 'Sélection effacée';
}

// ============ Recherche d'adresse (API Adresse data.gouv.fr) ============
// API publique gratuite, sans clé : https://adresse.data.gouv.fr/api-doc/adresse
const API_ADRESSE = 'https://api-adresse.data.gouv.fr/search/';
let suggestions = [];
let suggestFocus = -1;
let suggestDebounce = null;
let adresseMarker = null;

const adresseInput = document.getElementById('adresseInput');
const suggestBox = document.getElementById('suggestBox');

adresseInput.addEventListener('input', () => {
  clearTimeout(suggestDebounce);
  const q = adresseInput.value.trim();
  if (q.length < 3) { suggestBox.classList.remove('open'); suggestions = []; return; }
  suggestDebounce = setTimeout(() => fetchSuggestions(q), 220);
});

adresseInput.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    suggestFocus = Math.min(suggestFocus + 1, suggestions.length - 1);
    renderSuggestions();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    suggestFocus = Math.max(suggestFocus - 1, -1);
    renderSuggestions();
  } else if (e.key === 'Enter') {
    e.preventDefault();
    if (suggestFocus >= 0 && suggestions[suggestFocus]) {
      selectSuggestion(suggestions[suggestFocus]);
    } else {
      centrerSurAdresse();
    }
  } else if (e.key === 'Escape') {
    suggestBox.classList.remove('open');
    suggestFocus = -1;
  }
});

document.addEventListener('click', (e) => {
  if (!e.target.closest('.header-search')) {
    suggestBox.classList.remove('open');
  }
});

async function fetchSuggestions(q) {
  try {
    const url = `${API_ADRESSE}?q=${encodeURIComponent(q)}&limit=6&autocomplete=1`;
    const r = await fetch(url);
    const data = await r.json();
    suggestions = (data.features || []).map(f => ({
      label: f.properties.label,
      ctx: `${f.properties.context || ''} · ${f.properties.type || ''}`.trim(),
      lat: f.geometry.coordinates[1],
      lng: f.geometry.coordinates[0],
      postcode: f.properties.postcode || '',
      city: f.properties.city || ''
    }));
    suggestFocus = -1;
    renderSuggestions();
  } catch (err) {
    suggestions = [];
    suggestBox.classList.remove('open');
  }
}

function renderSuggestions() {
  if (suggestions.length === 0) {
    suggestBox.classList.remove('open');
    suggestBox.innerHTML = '';
    return;
  }
  suggestBox.innerHTML = suggestions.map((s, i) => `
    <div class="suggest-item ${i === suggestFocus ? 'focus' : ''}" data-action="suggestion" data-index="${i}">
      <div class="label">${escapeHtml(s.label)}</div>
      <div class="ctx">${escapeHtml(s.ctx)}</div>
    </div>
  `).join('');
  suggestBox.classList.add('open');
}

function selectSuggestion(s) {
  adresseInput.value = s.label;
  suggestBox.classList.remove('open');
  centrerCarte(s.lat, s.lng, s.label);
}

function centrerSurAdresse() {
  const q = adresseInput.value.trim();
  if (!q) return;
  if (suggestions.length > 0) {
    selectSuggestion(suggestions[0]);
  } else {
    fetchSuggestions(q).then(() => {
      if (suggestions[0]) selectSuggestion(suggestions[0]);
    });
  }
}

function centrerCarte(lat, lng, label) {
  map.flyTo([lat, lng], 17, { duration: 1.2 });
  // Marker temporaire à l'adresse
  if (adresseMarker) map.removeLayer(adresseMarker);
  adresseMarker = L.marker([lat, lng], {
    icon: L.divIcon({
      className: 'adresse-marker',
      html: '<div style="background:#16a34a;width:14px;height:14px;border-radius:50%;border:3px solid white;box-shadow:0 0 8px rgba(22,163,74,0.6);"></div>',
      iconSize: [14, 14],
      iconAnchor: [7, 7]
    })
  }).addTo(map).bindPopup(`<b>📍 ${label}</b><br><small>Passe en mode 🎯 Sélectionner et clique sur tes parcelles autour.</small>`).openPopup();
  statusEl.textContent = `📍 Centré sur : ${label}`;
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// Chargement initial : parcelle ZT0010 Val-Fouzon (Indre) — commune de démo neutre (vraie géométrie IGN)
chercherParcelle();

SF.action('centrer-adresse', () => centrerSurAdresse());
SF.action('mode', (el) => setMode(el.dataset.mode));
SF.action('fond', (el) => setFond(el.dataset.fond));
SF.action('chercher-parcelle', () => chercherParcelle());
SF.action('effacer-parcelles', () => effacerParcelles());
SF.action('ajouter-parcelle', (el) => ajouterAuxParcelles(el.dataset.payload));
SF.action('suggestion', (el) => selectSuggestion(suggestions[Number(el.dataset.index)]));
