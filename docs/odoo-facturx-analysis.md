# Analyse Odoo account_edi_facturx — pour SelfInvoice / self-factur-x-agri

Date : 22 avril 2026 — 14:30 (Europe/Paris)
Objet : extraction des patterns de conception pour notre implémentation Factur-X AGPL
Référence : Odoo 19.0, addons `account_edi_ubl_cii` (LGPL-3) + `l10n_fr_facturx_chorus_pro` (LGPL-3)

## 1. Architecture du module

Odoo a abandonné la voie "module Factur-X dédié" depuis la v16 : **un seul module `account_edi_ubl_cii` couvre tous les formats européens** (Factur-X CII 2.2, UBL BIS 3, XRechnung, NLCIUS, EHF3, E-FFF, A-NZ, SG). Les localisations (ex : `l10n_fr_facturx_chorus_pro`) ne font qu'ajouter des champs et contraintes spécifiques.

**Fichiers clés** (`addons/account_edi_ubl_cii/models/`) :
- `account_edi_common.py` — Modèle abstrait `account.edi.common` + constantes globales (`UOM_TO_UNECE_CODE`, `EAS_MAPPING`, `TAX_EXEMPTION_MAPPING`, `SUPPORTED_FILE_TYPES`).
- `account_edi_xml_cii_facturx.py` — Modèle abstrait `account.edi.xml.cii` spécialisé CII 2.2 Factur-X/ZUGFeRD.
- `account_edi_xml_ubl_20.py` / `ubl_21.py` / `ubl_bis3.py` / `xrechnung.py` — Un modèle abstrait par dialecte UBL, héritage en cascade.
- `account_move.py` — Étend `account.move` avec `ubl_cii_xml_id` (Many2one attachment) et `ubl_cii_xml_file` (Binary).
- `account_move_send.py` — Hooks `_hook_invoice_document_before/after_pdf_report_render` qui assemblent XML + PDF.
- `account_tax.py` — Ajoute `ubl_cii_tax_category_code` et `ubl_cii_tax_exemption_reason_code` sur `account.tax`.
- `res_partner.py` — Champ `invoice_edi_format` (Selection pluggable), `peppol_eas`, `peppol_endpoint`.
- `data/cii_22_templates.xml` — Template QWeb XML pour génération CII.

**Pattern pluggable** : chaque format est un `AbstractModel` Odoo héritant de `account.edi.common`. L'ajout d'un nouveau format = nouveau modèle abstrait + entrée dans la `Selection invoice_edi_format` sur `res.partner`. Le dispatcher est `res.partner._get_edi_builder(edi_format)` qui retourne l'instance du bon builder selon le code.

## 2. Génération Factur-X

**Libs utilisées** :
- `lxml.etree` pour construction/validation XML.
- Template QWeb (`cii_22_templates.xml`) rendu via `cleanup_xml_node()` d'Odoo — pas de `facturx-python` externe, Odoo a tout réimplémenté inline.
- `odoo.tools.pdf.OdooPdfFileReader` / `OdooPdfFileWriter` (wrapper maison autour de pypdf) pour embarquer le XML dans le PDF.
- Conversion PDF → PDF/A-3 via paramètre système `edi.use_pdfa=true` (utilise Ghostscript côté serveur).

**Workflow exact** (`account_move_send.py`) :
1. `_hook_invoice_document_before_pdf_report_render` : construit `xml_content` via le builder, stocke dans `invoice_data['ubl_cii_xml_attachment_values']`.
2. Le rendu PDF classique QWeb/wkhtmltopdf s'exécute normalement.
3. `_hook_invoice_document_after_pdf_report_render` :
   - Lit le PDF généré via `OdooPdfFileReader`.
   - `writer.addAttachment('factur-x.xml', xml_facturx, subtype='text/xml')` — embarque le XML en AF (Associated File) PDF/A-3.
   - Conversion PDF/A-3 si FR/DE.
4. Point clé : **un XML Factur-X est toujours généré silencieusement** même si le format choisi est UBL BIS 3, pour inter-portabilité (le PDF/A-3 reste lisible).

**Structure XML CII** : namespaces `rsm`, `ram`, `udt`. Profil utilisé : `urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended` (EN 16931 EXTENDED). Nom du XML attaché : `factur-x.xml` (FR) ou `zugferd-invoice.xml` (DE).

## 3. Plan comptable et mapping TVA

Odoo **ne mappe pas par plan comptable** — le mapping se fait sur `account.tax` directement via deux champs :
- `ubl_cii_tax_category_code` (UNTDID 5305) : `S` (standard), `Z` (zéro), `E` (exonéré), `AE` (reverse charge), `G` (export hors UE), `K` (intracom), `O` (hors champ), `L` (IGIC Canaries), `M` (Ceuta/Melilla), `B` (transféré Italie).
- `ubl_cii_tax_exemption_reason_code` (liste CEF VATEX-*) : codes article 132/135/143/151/261 CGI etc., obligatoire uniquement si catégorie ≠ S.

**Taux FR 20%/10%/5.5%/2.1%** : aucun traitement spécial. Tous marqués `S` (Standard), le taux numérique vient de `tax.amount`. Le XML contient `<ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>5.50</ram:RateApplicablePercent>`.

**Spécificités agricoles** : **AUCUN traitement dédié**. Pas de distinction produits bruts vs transformés, pas de lien avec Ekylibre, pas de gestion remboursement forfaitaire agricole (298 bis CGI). Les localisations françaises d'Odoo (`l10n_fr_account`) fournissent les taux standards mais pas la logique agricole.

**Génération** : `invoice._prepare_invoice_aggregated_taxes(grouping_key_generator=...)` regroupe les lignes par `(category_code, exemption_reason, amount, amount_type)`. Les taxes fixes (type `fixed`, ex : Recupel BE) sont extraites et converties en charges/allowances au niveau document.

## 4. Chorus Pro / PDP

**Chorus Pro** : module `l10n_fr_facturx_chorus_pro` (80 lignes, très minimaliste). Ajoute 3 champs sur `account.move` :
- `buyer_reference` → "Code de Service" Chorus Pro (CBC:BuyerReference en UBL).
- `purchase_order_reference` → "Engagement Juridique" (OrderReference/ID).
- `contract_reference` → "Numéro de Marché".

Contraintes ajoutées : SIRET obligatoire pour fournisseur FR, VAT obligatoire pour fournisseur non-FR, company_registry obligatoire pour client public. Détection via `_is_customer_behind_chorus_pro(partner)` (regarde le peppol_eas du client).

**PDP (Plateforme de Dématérialisation Partenaire)** : **PAS géré nativement**. Odoo passe par son propre proxy `account_edi_proxy_client` + intégration Peppol (module séparé, non couvert par account_edi_ubl_cii). Pour la réforme FR 2026, Odoo s'appuie sur Peppol-CTC (Continuous Transaction Control) via leur partenariat Peppol — pas de module PDP dédié à ce jour.

## 5. Erreurs / TODOs observés

- **PR #113696** : jusqu'à Odoo 16, impossible d'étendre `ir_actions_report` proprement pour ajouter un nouveau format UBL qui embarque le PDF. Fix : refacto du hook.
- **Commentaire dans le code** : `is_peppol_edi_format` marqué `# TODO remove in master` — instabilité du modèle res.partner.
- **Double génération Factur-X** : même si le format choisi est `ubl_bis3`, un second XML CII est généré pour embarquement PDF → coût CPU doublé, pas configurable.
- **Validation schématron** : déléguée à un service externe payant (ecosio) via `_export_invoice_ecosio_schematrons` — pas de validation locale.
- **Codes TVA exemption FR-CGI** : liste incomplète pour le cas agricole (pas de code pour forfait 298 bis, pas de code pour TVA sur marge).
- **UOM UNECE** : mapping `UOM_TO_UNECE_CODE` codé en dur, très limité, pas de litre/hectare/tête de bétail natif.
- **Pas de validation PDF/A-3 de sortie** : Odoo génère mais ne vérifie pas la conformité finale (veraPDF non intégré).

## 6. Enseignements pour SelfInvoice

1. **Un builder abstrait par dialecte, pas un module par format.** Une classe de base `EInvoiceBuilder` + sous-classes `FacturXBuilder`, `UBLBis3Builder`, etc. Héritage clair, pas de duplication.
2. **Découpler XML generation et PDF embedding.** Deux étapes distinctes avec hooks explicites (before/after PDF render). On doit pouvoir générer juste le XML sans PDF pour les tests.
3. **Mapping TVA au niveau "taux", pas "compte".** Sur chaque taux on stocke `category_code` + `exemption_reason` (listes fermées UNTDID/VATEX). Les comptes comptables restent séparés.
4. **Regroupement par clé de tax** (`grouping_key_generator`) pour agréger les lignes d'invoice par groupe de TVA cohérent avant écriture XML — élégant et réutilisable.
5. **Profil Factur-X configurable**. Odoo code en dur EXTENDED. On doit exposer MINIMUM / BASIC WL / BASIC / EN 16931 / EXTENDED selon le use-case.
6. **Valider localement avec veraPDF + schematron Factur-X** (pas de dépendance cloud payante). Officiel : `xsltproc` + `.sch` de AFNOR/FNFE-MPE.
7. **Préférer `facturx-python` (Alexis de Lattre, AGPL)** plutôt que réimplémenter PDF/A-3. Odoo a réinventé la roue car contrainte LGPL. On est AGPL, libre d'utiliser la lib reconnue FNFE.

## 7. Enseignements pour self-factur-x-agri (SelfFarm-Lite)

- **Ajouter les codes UNECE agricoles manquants** à notre mapping UOM : `HAR` (hectare), `LTR` (litre), `KGM` (kg), `TNE` (tonne), `NAR` (nombre d'animaux - "number of articles"), `H87` (pièce), `MTK` (m²), `BX` (carton). Odoo n'en a qu'une poignée.
- **Code VATEX pour forfait agricole 298 bis CGI** : aucun code officiel côté EN 16931 ne couvre proprement le remboursement forfaitaire. Documenter le choix (probable `VATEX-FR-CGI295` ou custom `VATEX-FR-CGI298BIS` en attendant homologation FNFE-MPE).
- **TVA 5.5% produits bruts vs 10% transformés** : exposer au niveau produit (champ `product.transformation_state = {brut, transforme}`) et dériver le taux automatiquement. Odoo ne gère pas, c'est à la main.
- **Anticiper lien Ekylibre** : schéma de données Lexicon → mapping direct vers `IncludedSupplyChainTradeLineItem` CII. On peut pré-remplir le XML à partir du journal cultural Ekylibre.
- **Cas "vente directe producteur"** : le client est souvent un particulier sans SIRET. Factur-X l'accepte (BuyerSpecifiedLegalOrganization optionnel), mais Chorus Pro non. Bien distinguer B2B/B2G/B2C dans le builder.
- **PDP agricole** : à terme surveiller Agreste / FranceAgriMer pour une PDP filière. En attendant, prévoir un adaptateur "PDP générique" agnostique (REST + OAuth2).
- **Factur-X MINIMUM/BASIC WL** : pour coopératives et ventes directes, MINIMUM suffit largement (24 champs). Ne pas imposer EXTENDED comme Odoo.

## 8. Sources consultées

- [Odoo 19.0 — account_edi_ubl_cii (code source)](https://github.com/odoo/odoo/tree/19.0/addons/account_edi_ubl_cii) — consulté 22/04/2026
- [Odoo 19.0 — l10n_fr_facturx_chorus_pro](https://github.com/odoo/odoo/tree/19.0/addons/l10n_fr_facturx_chorus_pro) — consulté 22/04/2026
- [account_edi_xml_cii_facturx.py (raw)](https://raw.githubusercontent.com/odoo/odoo/19.0/addons/account_edi_ubl_cii/models/account_edi_xml_cii_facturx.py)
- [account_edi_common.py (raw)](https://raw.githubusercontent.com/odoo/odoo/19.0/addons/account_edi_ubl_cii/models/account_edi_common.py)
- [account_move_send.py (raw)](https://raw.githubusercontent.com/odoo/odoo/19.0/addons/account_edi_ubl_cii/models/account_move_send.py)
- [account_tax.py (raw)](https://raw.githubusercontent.com/odoo/odoo/19.0/addons/account_edi_ubl_cii/models/account_tax.py)
- [PR #113696 — Fix ir_actions_report extensibilité Factur-X](https://github.com/odoo/odoo/pull/113696) — consulté 22/04/2026
- [Odoo docs — Electronic invoicing EDI](https://www.odoo.com/documentation/19.0/applications/finance/accounting/customer_invoices/electronic_invoicing.html)
- [OCA/edi — Discussion XRechnung vs Factur-X](https://github.com/OCA/edi/issues/138)
- [PyPI — odoo-addon-account-invoice-facturx (OCA alternative)](https://pypi.org/project/odoo-addon-account-invoice-facturx/)
- Spécifications Chorus Pro v4.22 (référencées dans le code Odoo, `communaute.chorus-pro.gouv.fr`)
