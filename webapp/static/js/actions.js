/* Comportements déclarés dans le HTML par des attributs data-*, la CSP interdisant
   le JavaScript inline. Les écouteurs sont posés sur document : le contenu que htmx
   insère après coup en bénéficie aussi.

   data-confirm="…"        sur un <form> ou son bouton : confirmation avant l'envoi
   data-action="nom"       au clic : une action ci-dessous, ou enregistrée par SF.action
   data-change="nom"       au changement d'un champ : idem
   data-reload-after="ms"  sur un élément htmx : recharge la page après sa requête
*/
(function () {
  "use strict";

  const actions = {
    reload: () => window.location.reload(),
    print: () => window.print(),
    "toggle-class": (el) => {
      document.querySelector(el.dataset.target).classList.toggle(el.dataset.class);
    },
    "class-if-unchecked": (el) => {
      document.querySelector(el.dataset.target).classList.toggle(el.dataset.class, !el.checked);
    },
    submit: (el) => el.form.submit(),
  };

  window.SF = {
    action(nom, fn) { actions[nom] = fn; },
  };

  function lance(nom, el, e) {
    const fn = actions[nom];
    if (fn) fn(el, e);
    else console.error("SF : action inconnue", nom);
  }

  document.addEventListener("submit", (e) => {
    const msg = (e.submitter && e.submitter.dataset.confirm) || e.target.dataset.confirm;
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-action]");
    if (el) lance(el.dataset.action, el, e);
  });

  document.addEventListener("change", (e) => {
    const el = e.target.closest("[data-change]");
    if (el) lance(el.dataset.change, el, e);
  });

  document.addEventListener("htmx:afterRequest", (e) => {
    const el = e.detail.elt.closest("[data-reload-after]");
    if (el) setTimeout(() => window.location.reload(), Number(el.dataset.reloadAfter));
  });
})();
