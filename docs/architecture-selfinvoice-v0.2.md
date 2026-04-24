# Architecture SelfInvoice v0.2 — spec maître

Date : 22 avril 2026
Objet : consolider en un document unique les choix techniques issus de 3 études
(Odoo Factur-X, benchmark libs Python, API Viva Wallet) pour piloter la session
de code du soir.

## 0. Rappel des 3 piliers stratégiques

Depuis `project_selfinvoice_strategy.md` (mémoire) :

1. **Souveraineté locale** — self-hosted, AGPL-3.0-or-later, pas de capture SaaS
2. **Factur-X natif** — conformité obligation française 2026 sans dépendre de Pennylane/Quadient
3. **Auto-réconciliation Viva** — webhook paiement → lettrage facture automatique, zéro saisie manuelle

## 1. Stack technique

| Couche | Choix | Justification |
|---|---|---|
| Langage | Python 3.12 | Stack Pierroons, cohérent SelfFarm |
| API web | FastAPI | Async, doc OpenAPI auto, léger |
| BDD | SQLite → PostgreSQL à l'échelle | Portabilité, fichier unique au début |
| ORM | SQLAlchemy 2.0 (core + ORM) | Standard, migrations alembic |
| Modèles métier | Pydantic v2 | Validation, sérialisation, cohérence avec FastAPI |
| Front | HTML + htmx + Tailwind CSS | Pas de framework JS lourd, SSR propre |
| PDF | WeasyPrint (HTML → PDF/A-3) | Déjà en prod self-dnja, fontes OK |
| Factur-X | **factur-x** (akretion) | Benchmark validé : commit récent, validation Schematron FR |
| Payments | Viva Wallet API v2 (OAuth2) | Canal unique Pierroons (feedback_viva_stripe.md) |
| Tests | pytest + pytest-cov + pytest-asyncio | Écosystème mature |
| Qualité | ruff + mypy | Lint + typage statique |
| Deploy | Docker Compose (RPI4 / VPS) | Portable, gitops-friendly |

## 2. Architecture modulaire (monorepo)

```
selfinvoice/                        # nouveau repo à créer
├── core/                           # modèles métier Pydantic
│   ├── invoice.py                  # Invoice, InvoiceLine, Client, Tax
│   ├── chart_of_accounts.py        # mapping PCG → codes Factur-X
│   └── payment.py                  # Payment, PaymentStatus, Reconciliation
├── builders/                       # pattern abstrait Odoo
│   ├── base.py                     # AbstractFormatBuilder (interface)
│   ├── facturx_basic.py            # profil BASIC (minimal conforme FR)
│   ├── facturx_en16931.py          # profil EN 16931 (recommandé)
│   └── ubl_peppol.py               # UBL pour B2B international (optionnel)
├── integrations/
│   ├── viva/                       # client Viva Wallet
│   │   ├── auth.py                 # OAuth2 client_credentials
│   │   ├── quickpay.py             # POST /checkout/v2/orders
│   │   ├── webhooks.py             # handler FastAPI + re-vérif
│   │   └── models.py               # Pydantic Viva*
│   └── chorus_pro/                 # portail public FR (plus tard)
├── api/                            # FastAPI
│   ├── routes/
│   │   ├── invoices.py
│   │   ├── payments.py
│   │   └── webhooks.py
│   └── templates/                  # Jinja2 HTML pour PDF + UI htmx
├── db/
│   ├── models.py                   # SQLAlchemy ORM
│   └── migrations/                 # alembic
└── tests/
```

## 3. Workflow métier type (création facture → paiement)

```
┌────────────────────────────────────────────────────────────────┐
│ 1. User crée Invoice via UI htmx (client, lignes, TVA)         │
│ 2. API POST /invoices → persist BDD                            │
│ 3. User clique "Générer Factur-X" :                            │
│    a. HTML → WeasyPrint → PDF classique                        │
│    b. facturx.generate_facturx_from_binary(PDF, XML CII)       │
│    c. XML CII construit via notre builder (pattern Odoo)       │
│    d. Signature PDF/A-3 + XML incorporé                        │
│    e. Validation XSD + Schematron FR (dans la lib akretion)    │
│    f. PDF/A-3 final stocké + lien téléchargement               │
│ 4. User clique "Demander paiement Viva" :                      │
│    a. integrations.viva.auth.get_token() → bearer OAuth2       │
│    b. quickpay.create_order(invoice_id, amount) → orderCode    │
│    c. URL https://www.vivapayments.com/web/checkout?ref=XXX    │
│    d. Mail client avec URL (ou QR code)                        │
│ 5. Client paie → Viva envoie webhook event 1796                │
│ 6. Webhook handler :                                           │
│    a. HTTP 200 OK rapide (< 5 s)                               │
│    b. Side-job : GET /transactions/{id} pour re-vérifier       │
│    c. Si status="F" : invoice.mark_paid(), créer Payment       │
│    d. lettrage automatique (Payment ↔ Invoice)                 │
│ 7. User peut exporter FEC (fichier écritures comptables)       │
└────────────────────────────────────────────────────────────────┘
```

## 4. Enseignements Odoo à reprendre

Du rapport `odoo-facturx-analysis.md` :

1. **Pattern AbstractBuilder pluggable** — une classe par format (Factur-X, UBL, CII). Interface commune : `build(invoice: Invoice) -> (xml: bytes, pdf: bytes)`.
2. **Clé de groupement taxes** — grouper les lignes par taux avant XML pour respecter la structure CII.
3. **Silencieusement embarquer Factur-X CII** même en format UBL pour inter-portabilité (trick Odoo utile pour Chorus Pro).
4. **Mapping direct taxe → UNTDID 5305** (S/Z/E/AE/G/K/O/L/M/B), pas par plan comptable. 5.5%, 10%, 20%, 2.1% sont tous `S` avec taux différent.
5. **Ajouter mapping UOM agricole** (HAR hectare, LTR, TNE tonne, NAR nombre d'animaux, MTK m², BX boîte) — pas présent chez Odoo.
6. **Exposer les 5 profils Factur-X** (MINIMUM / BASIC WL / BASIC / EN 16931 / EXTENDED) — Odoo code EXTENDED en dur.
7. **Valider localement** (veraPDF + schematron AFNOR via saxonche) — pas de cloud ecosio.

## 5. Viva API — points clés à implémenter

Du rapport `viva-api-study.md` :

### Auth
- OAuth2 client_credentials sur `{demo-,}accounts.vivapayments.com/connect/token`
- Token 1 h, pas de refresh → cache en RAM (dict `{access_token, expires_at}`)
- Scope : `urn:viva:payments:core:api:redirectcheckout`
- Secrets dans `.env` : `VIVA_CLIENT_ID`, `VIVA_CLIENT_SECRET`, `VIVA_SOURCE_CODE`, `VIVA_ENV` (demo/prod)

### QuickPay
```http
POST https://api.vivapayments.com/checkout/v2/orders
Authorization: Bearer <token>
Content-Type: application/json

{
  "amount": 12500,              // en centimes, int
  "sourceCode": "1234",
  "merchantTrns": "invoice_id=42",
  "paymentTimeout": 300,
  "customerTrns": "Facture F2026-042",
  "allowRecurring": false
}

→ 200 { "orderCode": 1234567890123456 }
→ URL finale : https://www.vivapayments.com/web/checkout?ref=1234567890123456
```

### Webhooks
- **Pas de HMAC** → re-vérif obligatoire via `GET /checkout/v2/transactions/{id}`
- Events : `1796` (payment created — `StatusId=F`), `1797` (failed), `1798` (reversal)
- Handshake initial : GET au register → répondre `{"Key":"<val>"}`
- Idempotence : unique `TransactionId`
- Statuts : **F** = finalisé/lettrage OK, A = autorisé mais pas capturé, X = annulé, R = refund, E = erreur

### Modèles Pydantic à créer ce soir
```python
class VivaCreateOrderRequest(BaseModel):
    amount: int = Field(ge=30, description="Centimes, min 0.30 €")
    sourceCode: str
    merchantTrns: str
    paymentTimeout: int = 300
    customerTrns: str | None = None

class VivaWebhookPayload(BaseModel):
    EventTypeId: int
    EventData: VivaTransactionEventData
    Created: datetime

class VivaTransactionEventData(BaseModel):
    TransactionId: str
    StatusId: Literal["F", "A", "X", "R", "E"]
    Amount: float  # euros, pas centimes ici
    OrderCode: int
    MerchantTrns: str | None = None
```

## 6. Plan de la session de code du soir

### Sprint 1 — Setup (30 min)
- `mkdir selfinvoice/` (nouveau repo ou sous-module MySelf)
- pyproject.toml + venv + install deps (`fastapi`, `sqlalchemy`, `pydantic`, `factur-x`, `weasyprint`, `httpx`, `alembic`)
- Structure dossiers (section 2)
- Licence AGPL-3.0 + README

### Sprint 2 — Modèles core (1 h)
- Pydantic : `Invoice`, `InvoiceLine`, `Client`, `Tax`, `Payment`
- SQLAlchemy : tables correspondantes + migration alembic initiale
- Plan compta agricole (réutiliser le YAML self-agri-book déjà fait)

### Sprint 3 — Builder Factur-X (2 h)
- Classe abstraite `AbstractFormatBuilder`
- `FacturXBasicBuilder` : profil BASIC (conforme FR minimal)
- Intégration lib `factur-x` (akretion) pour validation + attach PDF/A-3
- Mapping taxes UNTDID 5305
- Template HTML Jinja2 pour le PDF visible
- Test : facture test → PDF/A-3 + XML valide

### Sprint 4 — API FastAPI (1 h)
- Routes : `GET /invoices`, `POST /invoices`, `POST /invoices/{id}/facturx`
- UI htmx minimale : formulaire création facture + liste

### Sprint 5 — Viva (2 h)
- `integrations/viva/auth.py` OAuth2 + cache token
- `quickpay.py` création ordre + URL
- `webhooks.py` : route POST + handshake GET + re-vérif transaction
- Lettrage automatique

### Sprint 6 — Tests + docs (1 h)
- pytest unit tests des builders + Viva mock
- README SelfInvoice
- Update memory `project_selfinvoice_strategy.md`

**Total estimé** : 7-8 h de code. Ambitieux mais réalisable vu qu'on a les specs.

## 7. Interactions avec SelfFarm-Lite

SelfInvoice et SelfFarm-Lite sont frères :
- SelfInvoice = **général** (toute PME/TPE, pas que agri)
- `self-factur-x-agri` (SelfFarm-Lite) = **spécialisation agri** (TVA 5.5/10, UOM HAR/TNE, codes produits FranceAgriMer, etc.)

L'architecture AbstractBuilder permet de faire hériter `self-factur-x-agri` de `selfinvoice.builders.facturx_basic` en surchargeant seulement les spécificités.

Bidirectionnel :
- SelfInvoice utilise le PCG agricole de `self-agri-book` pour les comptes 7011-7014 agri
- Les factures de vente de chanvre sortent en Factur-X via SelfInvoice + extension agri

## 8. Licence et dépendances

- **Projet** : AGPL-3.0-or-later (cohérent MySelf)
- **Libs utilisées** :
  - `factur-x` (akretion) : AGPL-3.0 ✅ compatible
  - `drafthorse` : Apache 2.0 ✅ compatible (fallback)
  - `weasyprint` : BSD-3 ✅
  - `fastapi` : MIT ✅
  - `sqlalchemy` : MIT ✅
  - `pydantic` : MIT ✅

Aucun conflit de licence. On peut publier AGPL propre.

## 9. Ce qui reste en attente de décision

- **Multi-tenancy** : un SelfInvoice = 1 exploitation (mono), ou multi pour mutualiser entre plusieurs producteurs bio d'un même territoire ?
- **Chorus Pro direct ou PDP partenaire** ? (Pour B2G, futur)
- **Portail paiement alternatif** à Viva (si redondance nécessaire) ? SEPA QR (cf. `project_selfcashpay_idea.md`) comme 2e canal ?
- **Signature PDF** avec certificat ? (pour conformité juridique renforcée)

À arbitrer ce soir ou plus tard.
