# self-pa — réception des factures fournisseurs

Réception des factures entrantes via une **Plateforme Agréée** (PA), et
proposition d'écriture comptable pour validation humaine.

Depuis le 1er septembre 2026, toute entreprise assujettie à la TVA doit pouvoir
recevoir ses factures sous forme électronique (CGI art. 289 bis), via une
plateforme agréée. Les factures arrivent donc **structurées** : leurs montants
sont dans des champs, pas dans une image. Il n'y a rien à parser et rien à
envoyer à un service tiers pour le faire lire.

L'émission vit dans SelfInvoice. Ce module ne couvre que le sens entrant.

## Chaîne

```
plateforme agréée
      │
      ├── en_invoice (JSON EN 16931, déjà décodé)   ← chemin principal
      └── PDF Factur-X → XML embarqué → cii_reader  ← canal mail + contrôle croisé
      │
      ▼
 FactureRecue ──► controler()  ──► proposer()  ──► [ validation humaine ]
                  arithmétique     écriture ACH          │
                  déterministe     6xxx / 401            ▼
                                              self_agri_book.save_ecriture()
```

Le dernier maillon n'est jamais franchi automatiquement. Une écriture fausse ne
se voit pas dans un bilan ; une écriture absente, si.

## Relevé de l'API Super PDP

Mesuré en sandbox le 9 septembre 2026, en lecture seule. Aucune spécification
OpenAPI publique n'est exposée (`/openapi.json`, `/swagger.json` → 404) : ce
relevé vient de l'observation, il n'a pas valeur de contrat.

| Appel | Rend |
|---|---|
| `POST /oauth2/token` | `client_credentials`, jeton valable 1800 s, aucun scope |
| `GET /v1.beta/invoices` | `{count, data[], has_after, has_before}` |
| `GET /v1.beta/invoices?direction=in` | **les factures reçues** — filtre effectif |
| `GET /v1.beta/invoices?direction=out` | les factures émises |
| `GET /v1.beta/invoices/{id}` | détail + `en_invoice` + `events[]` |
| `GET /v1.beta/invoices/{id}/download` | le PDF Factur-X (`application/pdf`) |
| `GET /v1.beta/invoice_events?starting_after_id=` | flux d'événements, paginé |

`/v1.beta/companies`, `/v1.beta/me`, et les variantes `/pdf`, `/xml`, `/file`,
`/attachment` rendent 404. L'en-tête `Accept` n'est pas honoré : seule l'URL
`/download` change le type de contenu.

### `en_invoice` — la facture déjà décodée

La plateforme rend une structure EN 16931 normalisée, ce qui dispense de lire le
XML sur le chemin principal :

```
number · issue_date · type_code · currency_code · payment_due_date
notes[]              { subject_code, note }
process_control      { business_process_type, specification_identifier }
seller / buyer       { name, identifiers[], legal_registration_identifier,
                       vat_identifier, electronic_address, postal_address }
totals               { sum_invoice_lines_amount, total_without_vat,
                       total_vat_amount{value,currency_code},
                       total_with_vat, amount_due_for_payment }
vat_break_down[]     { vat_category_taxable_amount, vat_category_tax_amount,
                       vat_category_code, vat_category_rate }
lines[]              { identifier, invoiced_quantity, invoiced_quantity_code,
                       net_amount, price_details, vat_information,
                       item_information }
```

**Les montants sont des chaînes** (`"1863.79"`), jamais des nombres JSON nus.
C'est ce qui permet de les charger en `Decimal` sans passer par un `float` — un
détail qui décide de l'exactitude au centime. Le SIREN se lit dans
`legal_registration_identifier.value` (`scheme: "0002"`).

`events[].status_code` suit les statuts français : `fr:202` = reçue par la
plateforme.

## Pourquoi garder le lecteur CII

La plateforme décode déjà. `cii_reader` sert ailleurs :

- **le canal mail.** Pendant la transition, une part des fournisseurs continue
  d'envoyer un Factur-X en pièce jointe. Le guide pratique DGFiP du 09/07/2026
  (question 3) confirme qu'une telle facture reste payable, comptabilisable et
  déductible.
- **le contrôle croisé.** Le XML s'extrait du PDF téléchargé, et se lit
  indépendamment. Deux sources qui divergeraient signaleraient un problème que ni
  l'une ni l'autre ne peut voir seule. Vérifié sur une facture réelle : les deux
  chemins donnent les mêmes montants au centime.

## Déduplication

La clé est **`SIREN émetteur : numéro de facture`**, jamais l'empreinte du
fichier.

Pendant la transition, la même facture arrive par deux canaux — en PDF par mail,
puis en XML par la plateforme — avec deux empreintes différentes. Dédupliquer sur
le fichier laisserait passer le doublon, et le guide DGFiP en fait le risque
principal de la période : double paiement, double comptabilisation, **double
déduction de TVA** (questions 5 et 15).

`save_ecriture()` déduplique déjà sur `(source_module, source_id)` ; ce module
lui fournit `source_module="self_pa"` et `source_id="<siren>:<numéro>#<compte>"`,
le suffixe par compte reprenant le motif de `webapp/routes/invoice.py` pour les
factures ventilées sur plusieurs charges.

## Contrôle arithmétique

Déterministe, et sans confiance accordée à l'origine de la donnée :

- **strict** sur ce que la norme impose au centime : `TTC = HT + TVA` (BR-CO-15),
  total TVA = somme des TVA par catégorie (BR-CO-14) ;
- **tolérant à 0,01 €** sur un montant recalculé depuis un taux, où l'arrondi
  légal produit un écart légitime ;
- **jamais bloquant** sur l'écart entre la somme des lignes et le total HT : une
  remise globale ou des frais de port l'expliquent.

Une anomalie bloquante empêche toute proposition d'écriture.

## Configuration

```
SUPERPDP_ENV=sandbox            # indicatif — le mode dépend de la CLÉ, pas de l'URL
SUPERPDP_CLIENT_ID=
SUPERPDP_CLIENT_SECRET=
```

Application de type **confidentielle** : le flux `client_credentials` n'existe
que pour ce type, et le code tourne côté serveur, là où un secret peut rester
secret.

Chaque installation porte ses propres identifiants, sur sa propre machine. Rien
ne transite par un tiers.
