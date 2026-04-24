# Analyse Ekylibre — Inspiration conception SelfFarm-Lite

**Date** : 22 avril 2026  
**Version Ekylibre analysée** : 4.35.0 (AGPLv3)  
**Licence** : Aucun code repris — Analyse conceptuelle uniquement

---

## 1. Vue d'ensemble architecturale

Ekylibre est une application Rails monolithique structurée autour d'un système de modèles métier densément relationnels. L'architecture repose sur :

- **Rails ORM** avec associations complexes (has_many through, polymorphism)
- **State machines** pour les workflows métier
- **Bookkeeping** : hooks automatiques pour la comptabilité
- **Customizable/Providable** : mixins pour l'extensibilité
- **Lexicon** : nomenclature de référence (comptes, produits, indicateurs) chargée depuis une base externe
- **Multi-devise** : gestion de devise intégrée à chaque transaction

Architecture très spécifique à Rails qui contraste fortement avec une architecture Python simple. Points clés pour SelfFarm : simplicité > exhaustivité.

---

## 2. Modèles métier clés

### 2.1 Vente / Facturation

**Modèles** :
- `Sale` : document parent (brouillon, devis, commande, facture) — états : draft → estimate → order → invoice
- `SaleItem` : lignes de vente (produit, quantité, prix unitaire, réduction, taxes)
- `SaleNature` : type de vente (paramètres : délai de paiement, TVA, journal comptable, catalogue)
- `Shipment` : livraison associée à une vente (États : draft → ordered → prepared → given)

**Relations clés** :
- Sale ← SaleItem (nested)
- Sale → Client (Entity)
- Sale → SaleNature → Journal (pour comptabilité)
- Sale → Shipment (1-to-n, chaque vente peut avoir plusieurs livraisons)
- SaleItem → variant (ProductNatureVariant), tax, account (comptable), activity_budget

**Workflow** :
1. Brouillon : création, édition libre
2. Devis (estimate) : proposition au client
3. Commande (order) : confirmée
4. Facture (invoice) : invoiced_at défini → création automatique des écritures comptables
5. Crédit (credit) : remboursement partiel/total

**Enseignement pour SelfFarm-Lite** :
- Séparation claire états : brouillon → proposition → confirmation → facturation
- Items imbriqués dans le parent (optimise requêtes)
- Lien très fort vente-comptabilité dès la conception (bookkeep hook)
- Gestion taxes intégrée item-level, pas globale

### 2.2 Achat / Facture fournisseur

**Modèles** :
- `Purchase` : document parent (draft → order → invoice) + `PurchaseOrder`, `PurchaseInvoice` (sous-types)
- `PurchaseItem` : lignes (variant, qty, unit_amount, taxes, compte analytique)
- `PurchaseNature` : paramètres type d'achat
- `Reception` : réception de marchandise (liée à PurchaseOrder)

**Relations clés** :
- Purchase ← PurchaseItem (nested)
- Purchase → Supplier (Entity)
- PurchaseItem → variant, account, activity_budget, team (cost center)
- PurchaseItem → fixed_asset (si achat immobilisé)
- Reception → PurchaseOrder, items

**Workflow** :
1. Brouillon
2. Commande (ordered_at)
3. Réception (given_at) → création automatique écritures
4. Facture (invoiced_at)

**États spécialisés** :
- `tax_payability` : TVA au paiement ou à l'invoice
- `reconciliation_state` : rapprochement bancaire (to_reconcile, accepted, reconcile)

**Enseignement pour SelfFarm-Lite** :
- Cycle achat souvent découplé de la réception (3 documents)
- Items portent coûts analytiques (équipe, budget activité)
- Immobilisations gérées au niveau item
- État de rapprochement important pour la trésorerie

### 2.3 Production / Parcellaire / Intervention

**Modèles clés** :
- `Activity` : type d'activité (céréales, élevage) — durée annuelle/pérenne
- `ActivityProduction` : production spécifique (parcelle + activité + campagne + tactic)
  - Champs : support (parcelle), size_value, started_on, stopped_on, state
  - Géométrie : support_shape, headland_shape (PostGIS)
  - Lien : campaign, tactic, season
- `Parcel` : parcelle physique (land_parcel) — support de la production
- `Campaign` : campagne/année (harvest_year) — agrège activités et interventions
- `Intervention` : action culturale
  - procedure_name (spraying, sowing, etc.)
  - nature : request (planifiée) ou record (réalisée)
  - state : in_progress, done, validated, rejected
  - Champs temporels : started_at, stopped_at, working_duration
  - Paramètres : doers, inputs, outputs, tools, targets (via InterventionParameter)

**Relations complexes** :
- Activity ← ActivityProduction (n per activity)
- ActivityProduction → Campaign (many-to-many, via HABTM)
- ActivityProduction → ActivityTactic (planning itinerary)
- Intervention ← InterventionParameter (group structure)
  - Paramètres : doers (agents/machines), inputs (consommables), outputs (récoltes), targets (zones)
- Intervention → Activity, ActivityProduction, Campaign (many-to-many)

**Enseignement pour SelfFarm-Lite** :
- Hiérarchie : Activité > Production (réalisée) > Intervention (actions)
- Production = intersection de 3 axes : parcelle (support), activité (type travail), campagne (période)
- Interventions atomiques mais liées à plan plus large
- Paramètres d'intervention structurés (pas JSON plat) : groupes, nesting

### 2.4 Comptabilité

**Modèles** :
- `Journal` : (sales, purchases, bank, stocks, cash, payslip, closure)
  - Paramètres : used_for_affairs, used_for_gaps, used_for_tax_declarations
- `JournalEntry` : écriture (number, printed_on, state : draft/posted)
  - Devise triple : journal, real (exercice), absolute (global)
- `JournalEntryItem` : ligne d'écriture (account, debit, credit, resource_id/type)
- `Account` : plan comptable (nature : general/auxiliary)
  - usages : texte pour recherche rapide (clients, suppliers, banks, etc.)
  - Champs : number (unique), label, centralizing_account_name

**Plan comptable** :
- Chargé depuis Lexicon (nomenclature externe en base)
- Comptes agricoles prédéfinis (ex: "fixed_assets", "land_parcel_assets")

**Affair** : dossier client/fournisseur
- Regroupe : debit/credit, deals_count, état (ouvert/fermé)
- Calcul automatique solde = somme des deals (sales, purchases, paiements)
- Letter : lettrage (rapprochement manuel)

**Enseignement pour SelfFarm-Lite** :
- Grand livre très structuré (entry → items)
- Entrées comptables créées **automatiquement** via bookkeep hooks sur Sale/Purchase
- Gestion devise = complexe en Rails, simplifier en Python (monodevise initial)
- Relationship Sale → JournalEntry : 1-to-1 (pas de flexibilité)

---

## 3. Patterns architecturaux à reprendre (conceptuellement)

### 3.1 State Machines pour les workflows
Ekylibre utilise state_machine gem pour gérer transitions :
```ruby
# Exemple: Sale
state_machine :state, initial: :draft do
  state :draft, :estimate, :order, :invoice
  event :propose do
    transition draft: :estimate, if: :has_content?
  end
  event :invoice do
    transition [:draft, :estimate, :order] => :invoice, if: :has_content?
  end
end
```
**Pattern pour SelfFarm** : États explicites avec règles de transition. Facilite audit, undo.

### 3.2 Nested Items (composition)
Sale/Purchase/Reception portent des items imbriqués, pas JSON blobs :
```ruby
class Sale < ApplicationRecord
  has_many :items, class_name: 'SaleItem', dependent: :destroy
  accepts_nested_attributes_for :items
end
```
**Pattern** : Items liés 1-to-many avec suppression en cascade. Simplifie calcul totaux, validation.

### 3.3 Automatic Accounting via Bookkeep Hooks
À chaque state change (invoice), les écritures sont générées automatiquement :
```ruby
bookkeep do |b|
  b.journal_entry(self.nature.journal, ...) do |entry|
    entry.add_debit(label, client.account(:client).id, amount)
    items.each do |item|
      entry.add_credit(label, item.account.id, item.pretax_amount)
    end
  end
end
```
**Pattern** : Business logic (vente) déclenche automatiquement comptabilité. Pas de désynchronisation.

### 3.4 Type STI (Single Table Inheritance)
- Parcel → Shipment (outgoing), Reception (incoming)
- Purchase → PurchaseOrder, PurchaseInvoice

**Pattern** : Partage de schéma, spécialisation comportement. Utile pour types proches.

### 3.5 Polymorphic Relations
```ruby
belongs_to :resource, polymorphic: true  # JournalEntry peut pointer Sale ou Purchase
```
**Pattern** : Écriture comptable agnostique document. Mais complexité en requêtes.

### 3.6 has_and_belongs_to_many pour relations symétriques
```ruby
has_and_belongs_to_many :campaigns
has_and_belongs_to_many :activity_productions
```
**Pattern** : Intervention peut appartenir à N campagnes/productions. Table de jonction simple.

### 3.7 Customizable/Providable Mixins
```ruby
include Customizable   # custom_fields (JSONB)
include Providable     # provider (JSONB) pour données tierces
```
**Pattern** : Extensibilité sans migration. Pratique mais rend hard la sérialisation.

---

## 4. Patterns à éviter (ou simplifier fortement)

### 4.1 Complexité ORM relationnelle excessive
**Problème Ekylibre** : 
- 100+ modèles avec deep nesting
- Les associations sont denses (has_many through, polymorphic)
- Requêtes N+1 même avec includes (bugs courants)

**Pour SelfFarm** : Schéma plus plat, relations 1-to-N claires, pas de many-to-many sauf si crucial.

### 4.2 Devise multi-devise systématique
**Problème** :
- Chaque modèle : `refers_to :currency`, triple calculs (journal/real/absolute)
- Complexité énorme pour "peu de bénéfice" (plupart fermes monodevise)

**Pour SelfFarm** : Devise fixe au tenant/farm. Ajouter multi-devise plus tard si demande.

### 4.3 Hooks bookkeeping implicites
**Problème** :
- Logique comptable cachée dans modèles métier
- Difficile à auditer, tester, déboguer
- Side-effects non-évidentes

**Pour SelfFarm** : Comptabilité en couche séparée, appelée explicitement. Ex : `sale.record_accounting()` au lieu de hook.

### 4.4 JSONB non typé (custom_fields, provider)
**Problème** :
- Validations difficiles
- Migrations impossibles
- Sérialisation ad-hoc

**Pour SelfFarm** : Schéma de données strict dès le départ. JSONB seulement si vraiment extensible requis.

### 4.5 STI trop utilisé
**Ekylibre** : Sale/SaleOrder/SaleInvoice vs Parcel/Shipment/Reception
**Problème** : Table unique massive, requêtes type::= constantes

**Pour SelfFarm** : Héritage clair vs composition. Si 2-3 variantes, considérer modèles séparés.

### 4.6 Lexicon externe pour nomenclature
**Ekylibre** : Plan comptable, produits, indicateurs depuis gem `lexicon-common`
**Problème** : Dépendance externe, complexité bootstrap, coupling fort

**Pour SelfFarm** : Nomenclature en base applicative, migrable, simpler.

---

## 5. Synthèse — Principes clés pour SelfFarm-Lite

### Retenons :

1. **Workflow explicite via States**  
   Brouillon → Devis/Commande → Facture avec transitions claires. Facilite audit, reversal.

2. **Composition items plutôt que JSON**  
   Sale/Purchase portent des items relationnels, pas des blobs. Facilite calculs, validations, requêtes.

3. **Séparation métier-comptabilité, mais couplage intentionnel**  
   Vente crée automatiquement écriture (pas désynchronisation), mais logique en couche dédiée, testable.

4. **Production = (Parcelle + Activité + Campagne + Tactic)**  
   Hiérarchie ternaire claire pour planification. Intervention atomique = action dans production.

5. **Schéma relationnel strict, peu de polymorph/STI**  
   Modèles simples, requêtes évidentes, pas de N+1 hidden.

6. **Éviter multi-devise, JSONB non-typé, nomenclature externe**  
   Ces complexités Ekylibre font sens pour ERP généraliste, pas pour SelfFarm MVP.

### Différences clés SelfFarm-Lite vs Ekylibre :

| Aspect | Ekylibre | SelfFarm-Lite |
|--------|----------|--------------|
| **Language** | Ruby | Python |
| **ORM** | Rails ActiveRecord | SQLAlchemy / Django ORM |
| **Devise** | Triple (journal/real/absolute) | Monodevise ou tag simple |
| **Modèles** | 100+ densément liés | ~20-30 essentiels |
| **Comptabilité** | Hooks implicites | Service couche applicative |
| **Nomenclature** | Lexicon externe | Base applicative |
| **Extensibilité** | JSONB custom_fields | Schema migrations |
| **Multi-tenancy** | Non (per instance) | Oui (schema partitioning) |

---

## 6. Fichiers clés Ekylibre consultés

- `/app/models/sale.rb` : Workflow, bookkeeping
- `/app/models/purchase.rb` : Achat, taxes
- `/app/models/intervention.rb` : Intervention culturale
- `/app/models/activity_production.rb` : Production parcellaire
- `/app/models/journal_entry.rb` : Écritures comptables
- `/app/models/account.rb` : Plan comptable
- `/lib/ekylibre/lexicon.rb` : Nomenclature référence

**Conclusion** : Ekylibre est un ERP complet, excellent pour ferme complexe. SelfFarm-Lite doit viser 20% de complexité pour 80% de valeur agricole. Simplifié, scalable, maintenable.
