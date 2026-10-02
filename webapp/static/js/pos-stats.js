Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.font.size = 11;
Chart.defaults.color = '#9bb09f';
Chart.defaults.borderColor = '#1c302a';

const DONNEES = JSON.parse(document.getElementById('pos-stats-data').textContent);
const TOP = DONNEES.top;
const EVOL = DONNEES.evol;
const PALETTE = ['#2d5a3a','#4a7c5e','#86a890','#c4d4c9','#6a8070','#d4a056','#b85751','#6b8e9d','#a8c0ae','#3d6b4e'];

// Top produits (bar horizontal CA)
if (TOP.produits.length) {
  new Chart(document.getElementById('chartTopProduits'), {
    type: 'bar',
    data: {
      labels: TOP.produits.map(p => (p.emoji || '') + ' ' + p.nom),
      datasets: [{label:'CA (€)', data: TOP.produits.map(p => p.ca), backgroundColor:'rgba(45,90,58,0.85)', borderRadius:4}]
    },
    options: {
      indexAxis: 'y', responsive:true, maintainAspectRatio:false,
      plugins:{legend:{display:false}, tooltip:{callbacks:{label: c => c.parsed.x.toLocaleString('fr-FR') + ' € · ' + TOP.produits[c.dataIndex].qte + ' ' + TOP.produits[c.dataIndex].unite}}},
      scales:{x:{grid:{color:'#1c302a'}, ticks:{callback: v => v + ' €'}}, y:{grid:{display:false}}}
    }
  });

  // Répartition CA (donut)
  new Chart(document.getElementById('chartRepartition'), {
    type: 'doughnut',
    data: {
      labels: TOP.produits.map(p => p.nom),
      datasets: [{data: TOP.produits.map(p => p.ca), backgroundColor: TOP.produits.map((_,i) => PALETTE[i % PALETTE.length]), borderColor:'#0f1814', borderWidth:2}]
    },
    options: {responsive:true, maintainAspectRatio:false, cutout:'60%', plugins:{legend:{position:'bottom', labels:{usePointStyle:true, padding:8, font:{size:10}}}, tooltip:{callbacks:{label: c => c.label + ' : ' + c.parsed.toLocaleString('fr-FR') + ' €'}}}}
  });
}

// Évolution par semaine (bar)
if (EVOL.labels.length) {
  new Chart(document.getElementById('chartEvolution'), {
    type: 'bar',
    data: {labels: EVOL.labels, datasets: [{label:'CA hebdo (€)', data: EVOL.data, backgroundColor:'rgba(74,124,94,0.8)', borderRadius:4}]},
    options: {responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}, tooltip:{callbacks:{label: c => c.parsed.y.toLocaleString('fr-FR') + ' €'}}}, scales:{x:{grid:{display:false}}, y:{grid:{color:'#1c302a'}, ticks:{callback: v => v + ' €'}}}}
  });
}
