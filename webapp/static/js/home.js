// Theme global Chart.js
Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.font.size = 11;
Chart.defaults.color = '#9bb09f';
Chart.defaults.borderColor = '#1c302a';

// Données injectées server-side depuis /api/dashboard/stats (même source réutilisable).
// Règle : la ligne "plafond aides" n'a JAMAIS de valeur 0 (déjà filtré côté backend).
const DASH = JSON.parse(document.getElementById('home-data').textContent);

// ===== Bar chart revenus mensuels =====
new Chart(document.getElementById('chartRevenus'), {
  type: 'bar',
  data: {
    labels: DASH.chart_revenus.labels,
    datasets: [
      {label:'Recettes', data: DASH.chart_revenus.recettes, backgroundColor:'rgba(45,90,58,0.85)', borderRadius:4, borderSkipped:false},
      {label:'Charges', data: DASH.chart_revenus.charges, backgroundColor:'rgba(212,160,86,0.65)', borderRadius:4, borderSkipped:false}
    ]
  },
  options: {
    responsive:true, maintainAspectRatio:false,
    plugins: {
      legend:{position:'bottom', labels:{usePointStyle:true, padding:14, font:{size:11}}},
      tooltip:{backgroundColor:'#0f1814', titleColor:'#e8efe9', bodyColor:'#9bb09f', borderColor:'#2a4035', borderWidth:1,
        callbacks:{label: c => c.dataset.label + ' : ' + new Intl.NumberFormat('fr-FR').format(c.parsed.y) + ' €'}}
    },
    scales: {
      x:{grid:{display:false}, ticks:{color:'#6a8070'}},
      y:{grid:{color:'#1c302a', drawBorder:false}, ticks:{color:'#6a8070', callback: v => v + ' €'}}
    }
  }
});

// ===== Donut cultures =====
// Palette tournante si > 5 cultures
const CULTURE_COLORS = ['#2d5a3a','#4a7c5e','#86a890','#c4d4c9','#6a8070','#d4a056','#b85751','#6b8e9d'];
const culturesData = DASH.chart_cultures.data.length > 0 ? DASH.chart_cultures.data : [1];
const culturesLabels = DASH.chart_cultures.labels.length > 0 ? DASH.chart_cultures.labels : ['Aucune culture'];
new Chart(document.getElementById('chartCultures'), {
  type: 'doughnut',
  data: {
    labels: culturesLabels,
    datasets: [{
      data: culturesData,
      backgroundColor: culturesLabels.map((_, i) => DASH.chart_cultures.data.length > 0 ? CULTURE_COLORS[i % CULTURE_COLORS.length] : '#1c302a'),
      borderColor:'#0f1814', borderWidth:2
    }]
  },
  options: {
    responsive:true, maintainAspectRatio:false, cutout:'62%',
    plugins: {
      legend:{position:'bottom', labels:{usePointStyle:true, padding:8, font:{size:10.5}}},
      tooltip:{backgroundColor:'#0f1814', titleColor:'#e8efe9', bodyColor:'#9bb09f', borderColor:'#2a4035', borderWidth:1,
        callbacks:{label: c => c.label + ' : ' + c.parsed + ' ha'}}
    }
  }
});

// ===== Combo bar+line aides (1 colonne par aide) =====
// Règle : la ligne plafond ne descend jamais à 0 (filtrer aides à plafond > 0)
new Chart(document.getElementById('chartAides'), {
  type: 'bar',
  data: {
    labels: DASH.chart_aides.labels,
    datasets: [
      {type:'bar', label:'Perçu à ce jour (€)', data: DASH.chart_aides.percu,
       backgroundColor:'rgba(45,90,58,0.85)', borderRadius:4, order:2, maxBarThickness:60},
      {type:'line', label:'Plafond attendu (€)', data: DASH.chart_aides.plafond,
       borderColor:'#d4a056', backgroundColor:'rgba(212,160,86,0.1)', borderWidth:2.5,
       pointBackgroundColor:'#d4a056', pointBorderColor:'#0f1814', pointBorderWidth:1.5,
       pointRadius:4.5, pointHoverRadius:6, tension:0, fill:false, order:1}
    ]
  },
  options: {
    responsive:true, maintainAspectRatio:false,
    plugins: {
      legend:{position:'bottom', labels:{usePointStyle:true, padding:14, font:{size:11}}},
      tooltip:{backgroundColor:'#0f1814', titleColor:'#e8efe9', bodyColor:'#9bb09f', borderColor:'#2a4035', borderWidth:1,
        callbacks:{
          label: c => c.dataset.label + ' : ' + new Intl.NumberFormat('fr-FR').format(c.parsed.y) + ' €',
          afterLabel: c => {
            if (c.datasetIndex === 0) {
              const plafond = c.chart.data.datasets[1].data[c.dataIndex];
              const pct = plafond ? Math.round(c.parsed.y / plafond * 100) : 0;
              return '→ ' + pct + '% du plafond';
            }
            return '';
          }
        }
      }
    },
    scales: {
      x:{grid:{display:false}, ticks:{color:'#9bb09f', font:{size:10.5}}},
      y:{grid:{color:'#1c302a', drawBorder:false}, ticks:{color:'#6a8070', callback: v => (v/1000) + 'k €'}}
    }
  }
});

// ===== Gauge demi-cercle =====
new Chart(document.getElementById('chartGauge'), {
  type: 'doughnut',
  data: {
    labels: ['Saisi', 'Restant'],
    datasets: [{
      data:[DASH.gauge.pct, Math.max(0, 100 - DASH.gauge.pct)],
      backgroundColor:['#2d5a3a', '#1c302a'], borderWidth:0,
      circumference:180, rotation:270
    }]
  },
  options: {responsive:true, maintainAspectRatio:false, cutout:'78%', plugins:{legend:{display:false}, tooltip:{enabled:false}}}
});
