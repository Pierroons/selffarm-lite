# Conformité PAF — SelfAgriBook (hub compta SelfFarm-Lite)

Document de procédure pour la **Piste d'Audit Fiable** (PAF) au sens du
**CGI art. 289-VII**. À fournir en cas de contrôle DGFIP.

> **Pour qui ?** — exploitants agricoles français au régime réel utilisant
> SelfFarm-Lite pour l'émission de factures électroniques B2B et la tenue de
> leur comptabilité.

---

## 1. Cadre légal

### 1.1 Exigences fondamentales

Le **CGI art. 289-VII** impose, pour qu'une facture électronique soit légalement
valide, que **trois conditions** soient garanties :

1. **Authenticité de l'origine** : preuve de l'identité de l'émetteur
2. **Intégrité du contenu** : aucune modification depuis l'émission
3. **Lisibilité** : visualisation humaine possible à tout moment

### 1.2 Méthode de garantie retenue : Piste d'Audit Fiable (PAF)

L'article 289-VII admet **trois méthodes** :

| Méthode | Coût | Adopté |
|---|---|---|
| Signature électronique qualifiée (eIDAS) | 80-1500 €/an | non (V3) |
| EDI structuré conforme | élevé | non |
| **Piste d'Audit Fiable** | gratuit (open source) | ✅ **oui** |

### 1.3 Sources doctrinales

- **CGI art. 289-VII** — facturation électronique
- **CGI art. 289-II** — numérotation séquentielle continue
- **CGI art. 242 nonies A** — mentions obligatoires
- **CGI art. L102 B** — conservation 6 ans
- **BOI-CF-COM-10-10-30** — bulletin officiel des finances publiques (PAF)
- **BOI-TVA-DECLA-30-20-30** — facturation électronique
- **Règlement ANC 2019-01** — plan comptable agricole

---

## 2. Périmètre de la PAF

La PAF documentée couvre :

- ✅ Factures de **vente B2B** émises depuis SelfInvoice (PDF/A-3 + XML CII)
- ✅ Écritures comptables auto-générées dans le hub SelfAgriBook
- ✅ Audit log de toutes les actions de création / verrouillage
- ❌ Hors périmètre : caisse B2C marché (futur module SelfPOS, NF525)
- ❌ Hors périmètre : signature qualifiée eIDAS (V3 prévu)

---

## 3. Contrôles techniques implémentés

### 3.1 Numérotation séquentielle continue (CGI art. 289-II)

- Table `compteurs_factures(annee, prefix, dernier_numero)` en SQLite
- Helper `next_numero_facture(annee, prefix='F')` — transaction `BEGIN IMMEDIATE`
  → atomicité garantie même en concurrence
- L'utilisateur ne peut **pas** saisir un numéro libre (champ form `readonly`)
- Compteurs séparés par année et par préfixe (`F-`, `AV-` pour avoirs)
- Format extensible : `F-AAAA-NNNN` (passe à 5 chiffres si > 9999/an)
- Initialisation depuis l'historique : `MAX(numero existing) + 1` au boot

**Vérification** : aucun saut, aucun doublon possibles.
Audit DGFIP : `SELECT numero_piece FROM ecritures_comptables WHERE source_module='self_invoice' ORDER BY id` → suite continue.

### 3.2 Hash chain cryptographique (intégrité)

Chaque écriture stocke trois hash SHA256 :

| Colonne | Calcul |
|---|---|
| `hash_data` | SHA256 du payload canonical JSON (clés triées, format déterministe) |
| `hash_previous` | `hash_data` de la **précédente** écriture (chaîne) |
| `hash_pdf` | SHA256 du PDF Factur-X émis (preuve binaire) |

**Propriété** : modifier une écriture passée invalide son `hash_data` ET tous les
`hash_previous` des suivantes. Détection en O(n) via `verify_chain()`.

**Vérification** :
- Page web : http://localhost:8001/compta/integrite → ✓ ou ✗ avec ligne fautive
- Endpoint API : `GET /compta/integrite` (HTML)
- Helper : `from self_agri_book.storage import verify_chain; verify_chain()`

### 3.3 Verrouillage post-émission (immutabilité)

- Colonne `locked INTEGER` (0/1) + `locked_at TEXT`
- Une facture émise via SelfInvoice = `locked=1` **immédiatement** dans la même
  transaction que l'INSERT
- Helper `lock_ecriture(id)` pour verrouillage différé (saisie manuelle)
- **Politique annulation** : pour annuler une facture verrouillée, émettre un
  **avoir** (préfixe `AV-`, compte 709 — Rabais, Remises et Ristournes accordés).
  **Jamais** de modification ou de suppression.

### 3.4 Audit log append-only

- Table `audit_log(id, timestamp, actor, action, target_type, target_id, details_json)`
- **Triggers SQLite** `RAISE(ABORT)` sur UPDATE et DELETE → tentative de modif
  ou d'effacement échoue en SQLite, retour erreur applicative
- Hooks automatiques sur :
  - `save_ecriture` → `action='ecriture.create'`
  - `lock_ecriture` → `action='ecriture.lock'`
  - (Restore backup, reset démo, etc. — V2)
- Lecture via `list_audit_log(limit=N)`

**Vérification** :
```sql
SELECT * FROM audit_log ORDER BY id DESC LIMIT 10;
-- DELETE FROM audit_log;  -- → SQLite Error: audit_log is append-only
-- UPDATE audit_log SET action='hack' WHERE id=1;  -- → idem
```

### 3.5 Conservation et format pérenne

- **Stockage** : SQLite (format ouvert, lisible des décennies)
- **Localisation** : `~/.selffarm/compta.db` (variable `SELFFARM_COMPTA_DB`)
- **Backup ZIP** signé SHA256 dans manifest + restauration vérifiée
- **PDF Factur-X** PDF/A-3 (norme ISO 19005-3) + XML CII embarqué
- **Durée** : 6 ans minimum (CGI art. L102 B), backups recommandés indéfinis

---

## 4. Procédure opérationnelle (lien commande → facture → paiement → écriture)

```
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ Commande client │ → │ Émission facture│ → │ Paiement reçu   │ → │ Écriture compta │
│  (verbal/email/ │   │  /invoice/nouv. │   │ (relevé bancaire│   │  auto 411/701   │
│   bon de cmde)  │   │ → PDF Factur-X  │   │  PDF SG parsé)  │   │  + 512/411      │
└─────────────────┘   └─────────────────┘   └─────────────────┘   └─────────────────┘
        │                     │                     │                     │
        └─ archivé email      └─ stocké hash_pdf    └─ source_module=     └─ chaîne crypto
           ou papier             dans compta           self_banking          + audit_log
                                                       + lettrage 411
```

### 4.1 Émission de facture

1. Utilisateur ouvre `http://localhost:8001/invoice/nouvelle`
2. Le numéro est **calculé serveur** depuis `compteurs_factures` (lecture seule
   côté UI, atomique côté DB)
3. L'utilisateur saisit client + lignes + régime
4. Soumission `POST /invoice/creer` :
   - `next_numero_facture()` incrémente le compteur (transaction)
   - Génération PDF Factur-X via WeasyPrint + template canonical
   - Calcul `hash_pdf = SHA256(pdf_bytes)`
   - `save_ecriture(..., hash_pdf=..., locked=True)` → écriture verrouillée immédiatement
   - Audit log `ecriture.create` avec `details.locked=true`
5. Le PDF est servi à l'utilisateur, l'écriture est en DB (verrouillée, signée,
   chaînée)

### 4.2 En cas de litige client → annulation

**Interdit** : modifier la facture émise, supprimer l'écriture.

**Procédure conforme** :
1. Émettre un **avoir** : préfixe `AV-` (compteur séparé), compte `709 — Rabais
   accordés`, montant en négatif côté client
2. Lien de l'avoir vers la facture initiale dans `metadata_json.facture_originale`
3. Si avoir partiel + nouvelle facture : émettre une nouvelle facture avec
   numéro standard `F-AAAA-NNNN`

### 4.3 Réception paiement (V2, prévu sprint suivant)

1. Import du relevé bancaire SG via parser PDF (`self_banking`)
2. Lettrage automatique : virement reçu = montant TTC d'une facture
   `source_module='self_invoice'` non lettrée → écriture `512 / 411`
3. Audit log `paiement.recu` lié à la facture

---

## 5. Vérifications en cas de contrôle DGFIP

### 5.1 Niveau 1 — Vue d'ensemble

Le contrôleur ouvre `/compta/integrite` et vérifie :

- ✓ **Verdict global** : "Chaîne intègre" en vert
- ✓ **Stats** : nb écritures, nb verrouillées, % avec hash
- ✓ **Audit log** : pas d'anomalie, dates cohérentes
- ✓ **Toutes les factures `self_invoice` sont verrouillées**

### 5.2 Niveau 2 — Lecture de la DB

Le contrôleur peut accéder directement à `~/.selffarm/compta.db` avec n'importe
quel client SQL (sqlite3 CLI, DB Browser, DBeaver) :

```sql
-- Numérotation continue ?
SELECT numero_piece FROM ecritures_comptables
WHERE source_module='self_invoice'
ORDER BY id;

-- Toutes les factures verrouillées ?
SELECT id, numero_piece, locked, locked_at
FROM ecritures_comptables
WHERE source_module='self_invoice' AND locked=0;
-- → DOIT retourner 0 ligne

-- Audit log non altéré ?
SELECT id, timestamp, action, target_type, target_id
FROM audit_log
ORDER BY id ASC LIMIT 50;
```

### 5.3 Niveau 3 — Vérification cryptographique manuelle

```bash
# Recalcul du hash d'une écriture
PYTHONPATH=modules python -c "
from self_agri_book.storage import verify_chain
r = verify_chain()
print(r)
"
```

Sortie attendue :
```python
{'valid': True, 'nb_ecritures': 42, 'nb_locked': 38, 'broken_at': None, 'reason': None}
```

### 5.4 Niveau 4 — Export FEC officiel

`GET /compta/export-fec?siren=NNNNNNNNN` génère un fichier conforme :
- Format texte tab-separated UTF-8
- 18 colonnes obligatoires (BOI-CF-IOR-60-40-10)
- Nom : `FEC_{siren}_{date_fin_exercice}.txt` (art. L47 A-I LPF)
- Importable directement par les outils DGFIP (Test Compta Demat)

---

## 6. Limites assumées

| Limite | Mitigation prévue |
|---|---|
| Pas de signature eIDAS qualifiée | V3 — intégration certificat user optionnel |
| Pas d'horodatage qualifié RFC 3161 | V3 — TSP eIDAS ~50 €/an |
| `audit_log` lié à un seul utilisateur (mono-user) | V2 — multi-tenant |
| Pas de réplication temps réel | V2 — sync Git pour catalogues + backup régulier |
| Architecture mono-machine | Volontaire — souveraineté locale, pas de SaaS |

---

## 7. Tests automatisés

40 tests pytest couvrent les contrôles techniques :

```bash
PYTHONPATH=modules pytest modules/self_agri_book/tests/test_storage.py -v
```

Cas couverts :
- Numérotation séquentielle (continuité, atomicité, multi-année, multi-préfixe)
- Hash chain (calcul, lien previous, détection altération)
- Verrouillage (à la création, post-création, no-op si déjà locked)
- Audit log (création auto, append-only UPDATE/DELETE refusés)
- Migrations versionnées (idempotence, ordre)
- Roundtrip backup/restore préserve l'intégrité

---

## 8. Contacts & responsabilité

- **Responsable de la PAF** : exploitant·e (utilisateur·rice de SelfFarm-Lite)
- **Code source** : https://github.com/Pierroons/selffarm-lite (AGPL-3.0-or-later)
- **Issues / questions** : https://github.com/Pierroons/selffarm-lite/issues
- **Site projet** : https://selffarm.my-self.fr
- **Écosystème global** : https://my-self.fr

---

**Version document** : 1.0  
**Date** : 26 avril 2026  
**Couvre les versions SelfFarm-Lite** : ≥ 0.1.0-dev (post-migrations 1, 2, 3)
