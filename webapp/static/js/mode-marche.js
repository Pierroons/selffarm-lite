let lastSignature = '';

async function refreshHotspotStatus() {
  try {
    const r = await fetch('/api/pos/hotspot-status');
    const data = await r.json();
    const container = document.getElementById('cardsContainer');

    if (!data.any_lan || !data.ips || data.ips.length === 0) {
      container.innerHTML = `
        <div class="qr-card">
          <div class="qr-box"><span class="placeholder">⚠ Aucune connexion réseau détectée<br>Branche ton tel en USB, active le hotspot, ou connecte une box.</span></div>
          <div class="info"><p>Le PC doit être sur un réseau partagé avec le tel.</p></div>
        </div>`;
      lastSignature = '';
      return;
    }

    // Évite de re-render (et recharger les QR) si rien n'a changé
    const sig = data.ips.map(i => i.interface + i.ip).join('|');
    if (sig === lastSignature) return;
    lastSignature = sig;

    let html = '';
    for (const ipInfo of data.ips) {
      const isReco = ipInfo.ip === data.recommended_ip;
      const qrResp = await fetch('/api/pos/qr-code?url=' + encodeURIComponent(ipInfo.pwa_url));
      const qrSvg = await qrResp.text();
      html += `
        <div class="qr-card ${isReco ? 'reco' : 'dim'}">
          <div class="qr-box">${qrSvg}</div>
          <div class="info">
            <div class="iface-type">${ipInfo.label} · <code>${ipInfo.interface}</code></div>
            <h3>${ipInfo.stable ? 'Connexion stable' : 'Connexion WiFi'}${isReco ? '<span class="badge-reco">✓ Recommandée</span>' : ''}</h3>
            <p>Scanne ce QR avec ton tel, ou tape l'URL dans Chrome :</p>
            <code>${ipInfo.pwa_url}</code>
            ${!ipInfo.stable ? '<p style="color:var(--warm-amber); font-size:11.5px; margin-top:8px;">⚠ Le WiFi hotspot peut décrocher (veille tel). Préfère le câble USB si possible.</p>' : ''}
          </div>
        </div>`;
    }
    container.innerHTML = html;
  } catch (err) {
    document.getElementById('cardsContainer').innerHTML =
      '<div class="qr-card"><div class="qr-box"><span class="placeholder">Erreur : ' + err.message + '</span></div><div class="info"></div></div>';
  }
}

refreshHotspotStatus();
setInterval(refreshHotspotStatus, 5000);
