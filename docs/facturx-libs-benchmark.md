# Benchmark libs Factur-X Python

Date : 22 avril 2026 — 14:30 (Europe/Paris)
Objet : choisir la lib de génération Factur-X pour SelfInvoice / self-factur-x-agri

## Tableau comparatif

| Critère | factur-x (akretion) | drafthorse (pretix) | factur-x-ng (invoice-x) |
|---|---|---|---|
| Licence | BSD | Apache 2.0 | BSD (fork) |
| Dernière release | 4.2 — 23 mars 2026 | 2025.2.0 — 15 sept 2025 | Aucune release taguée |
| Dépendances principales | pypdf, lxml, saxonche (v4+) | lxml (PDF via code forké de factur-x) | PyPDF2/3, lxml |
| Profils Factur-X (MINIMUM, BASIC WL, BASIC, EN 16931, EXTENDED) | MINIMUM, BASIC WL, BASIC, EN 16931, EXTENDED + Order-X | ZUGFeRD 2.3 / Factur-X EXTENDED (pas de validation par profil) | MINIMUM, BASIC WL, BASIC, EXTENDED (ancien) |
| Génération XML CII | Oui (via templates XSD officiels) | Oui (modélisation 1:1 CII) | Oui (basique) |
| Attachement PDF/A-3 | pypdf (depuis v3.0, remplace PyPDF4) | Code PDF forké de factur-x (lxml + pypdf-like) | PyPDF2 (obsolète) |
| Validation XML vs XSD | Oui (`xml_check_xsd`, CLI `facturx-xmlcheck`) | Oui (automatique sur output) | Partielle |
| Validation Schematron | Oui (depuis v4.0 via saxonche) | Non | Non |
| Validation PDF/A-3 | Partielle (respecte si input conforme) | Partielle | Non |
| Support UBL Peppol | Non (pas officiel) | Non (focus ZUGFeRD/XRechnung) | Non |
| Support XRechnung | Indirect | Oui (schéma officiel ajouté nov 2025) | Non |
| Étoiles GitHub | 286 | 168 | 40 |
| Dernière activité commit | 23 mars 2026 | 27 nov 2025 | >2 ans (mort) |
| Issues ouvertes | 7 | 5 | Inactive |
| Tests unitaires inclus | Oui (changelog mentionne tests, intégrés au package) | Oui (`tests/` + `example.py`) | Oui (legacy) |
| Documentation | README.rst complet (install, CLI, webservice Flask, changelog détaillé) | README avec exemples parsing + génération | README minimal |
| Exemples pratiques | `generate_from_file()`, CLI `facturx-*`, webservice Flask | `example.py`, snippets README | Peu |
| Compatible Python 3.12+ | Oui (fix explicite v4.1, mars 2026) | Officiellement 3.7-3.10 (fonctionne 3.12 en pratique) | Non confirmé |
| Maintainer | Alexis de Lattre (Akretion, FR) | Équipe pretix (DE) | Abandonné |

## Tests qualité par lib

### factur-x (akretion) — 4.2
**Points forts :**
- Activement maintenu (commit il y a moins d'un mois, bug-fix #68 sur la fuite XSD)
- Couvre les 5 profils Factur-X + Order-X (bons de commande)
- Validation XSD **et** Schematron (saxonche), le combo exigé par Chorus Pro
- CLI intégrés (`facturx-pdfgen`, `facturx-xmlcheck`, `facturx-pdfextractxml`)
- Contexte français natif : auteur Akretion (intégrateur Odoo FR), TVA multi-taux gérée via templates CII
- BSD = intégration AGPL sans friction

**Points faibles :**
- Dépendance saxonche (~70 Mo) pour schematron, optionnelle mais lourde
- Pas de support UBL Peppol natif (si besoin Europe hors FR/DE)
- API orientée "générer depuis fichier XML" ; la construction programmatique du XML se fait à la main ou via templates Jinja

### drafthorse (pretix) — 2025.2.0
**Points forts :**
- API Pythonic propre : modélisation objet 1:1 du CII, attributs typés, sérialisation lxml fluide
- Idéal pour construire le XML **depuis Pydantic / dataclasses** (mapping direct)
- Support XRechnung officiel (nov 2025), validation XSD auto
- Base de code stable (pretix = billetterie open source mature)

**Points faibles :**
- Pas de validation par profil : génère un EXTENDED même si data = MINIMUM
- Focus ZUGFeRD/DE : pas de helpers français (codes TVA FR, SIRET, Chorus Pro)
- Pas de CLI, pas de schematron, pas de PDF/A-3 compliance check
- Classifiers PyPI s'arrêtent à Python 3.10 (signal de maintenance moindre côté compat)

### factur-x-ng (invoice-x)
Fork ancien, pas de releases, dernier commit >2 ans. **À écarter.**

## Reco finale

**Choix : `factur-x` (akretion) v4.2** comme moteur de génération et validation Factur-X.

Raison :
1. Seule lib avec validation XSD **+ Schematron** à jour (prérequis dépôt Chorus Pro sans rejet).
2. Couvre les 5 profils officiels, dont EN 16931 et EXTENDED attendus pour un usage agri pro (micro-BA → réel avec détails TVA 20/10/5,5).
3. Maintenance active française (Akretion), compatible Python 3.12+, licence BSD compatible AGPL.
4. Écosystème Odoo = garantie de continuité long terme.
5. CLI utilisables pour tests manuels et intégration CI.

**Intégration FastAPI/Pydantic recommandée :** construire le XML CII via `drafthorse` (objets typés, mapping direct depuis modèles Pydantic SelfInvoice), puis passer le XML résultant à `factur-x` pour **validation XSD+Schematron** et **attachement PDF/A-3**. Le duo combine l'ergonomie DE avec la rigueur FR.

**Fallback :** `drafthorse` seul si on accepte une validation XSD minimale et qu'on ajoute manuellement un wrapper pypdf/pikepdf pour l'attachement PDF/A-3. Option viable pour un MVP, mais impose de réécrire le check Schematron si Chorus Pro devient strict.
