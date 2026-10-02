(function(){
  var el = document.getElementById('backup-alert-banner');
  if (!el) return;
  var poll = setInterval(function(){
    fetch('/backup/health').then(function(r){ return r.json(); }).then(function(h){
      if (h && !h.alert) {
        clearInterval(poll);
        el.style.borderColor = 'var(--accent-200)';
        el.style.background = 'rgba(45,90,58,0.12)';
        document.getElementById('bab-icon').textContent = '✅';
        document.getElementById('bab-title').textContent = 'Sauvegarde rattrapée';
        document.getElementById('bab-msg').textContent = 'Tes données sont de nouveau à l\'abri.';
        document.getElementById('bab-hint').textContent = '';
        var a = document.getElementById('bab-arrow'); if (a) a.style.color = 'var(--accent-200)';
      }
    }).catch(function(){});
  }, 12000);
})();

