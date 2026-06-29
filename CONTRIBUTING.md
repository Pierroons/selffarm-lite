# Contribuer à SelfFarm-Lite

Merci de ton intérêt ! Quelques règles, surtout côté **données**.

## 🔒 Règle d'or : aucune donnée réelle dans le dépôt

Ce dépôt est **public**. N'y commite **jamais** :

- une **identité réelle** (nom civil, prénom+nom de quelqu'un),
- une **adresse**, commune + code postal réels, coordonnées GPS d'une exploitation,
- un **email perso**, un **téléphone**, un **IBAN/RIB** réel,
- une **IP privée** d'infra (`192.168.x.x`…), un **chemin disque** local, un nom de serveur interne,
- un **nom de domaine / business** personnel,
- un **secret** (clé API, token, mot de passe, contenu de `.env`).

Pour les **démos**, utilise uniquement des **données fictives** : personnages d'exemple
(`Marie DUPONT`), communes neutres, IBAN `FR76 0000 0000 0000 0000 0000 000`, etc.

Tes données personnelles de travail vont dans `_perso/` (gitignoré, jamais déployé).

## 🛡️ Protection automatique (obligatoire)

Le dépôt est protégé par [gitleaks](https://github.com/gitleaks/gitleaks) :

```bash
sudo apt install gitleaks      # une fois
./scripts/install-hooks.sh     # active le hook pre-commit
```

- Un **hook pre-commit** bloque localement tout commit contenant une donnée sensible.
- Une **CI GitHub Actions** (`.github/workflows/gitleaks.yml`) re-scanne chaque push/PR et
  **refuse le merge** en cas de fuite — la barrière s'applique à tout le monde.
- Règles dans `.gitleaks.toml` ; faux positifs connus dans `.gitleaksignore`.

## 🧱 Architecture — noyau agnostique du métier

SelfFarm vise « **core + verticales** » : un noyau réutilisable (compta, Factur-X,
caisse, backup) + des verticales métier (agriculture aujourd'hui ; d'autres demain).
Pour préserver cette portabilité :

- **Le noyau ne connaît pas le métier.** Aucun vocabulaire ni concept agricole en dur
  dans `self_agri_book` (hub compta), `self_invoice`, `self_backup`, `self_pos` — le hub
  agrège des écritures `701/706…` sans savoir d'où elles viennent.
- Le métier vit dans les **verticales** (`self_dnja`, `self_aid`, `self_culture`…) et le
  **front**, jamais dans le moteur. On parle d'« établissement », pas d'« exploitation ».
- Les **référentiels** (plan comptable, aides) sont des **données** chargées depuis un
  chemin configurable, pas du code.
- Avant d'ajouter au noyau : « un autre métier l'utiliserait-il tel quel ? ». Si non →
  c'est une verticale ou du front.

## 🚀 Déploiement

Le déploiement en production est réservé au mainteneur (`scripts/deploy.sh`, audit OPSEC
intégré). Les contributions passent par **Pull Request** sur `develop`.

## Commits

Configure ton email git en **noreply GitHub** pour ne pas exposer ton adresse :
`git config user.email "<id>+<login>@users.noreply.github.com"`.
