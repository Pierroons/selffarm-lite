"""
Le geste complet : récupérer les factures reçues, puis les comptabiliser.

Deux fonctions, deux moments, et la frontière entre les deux est le sujet de ce
module.

`recuperer_nouvelles()` est ce que déclenche le bouton du matin. Elle interroge
la plateforme, lit, contrôle, enregistre — et s'arrête là. Aucune écriture
comptable n'en sort.

`valider()` est ce qu'un humain déclenche après avoir regardé une facture à côté
de son écriture proposée. C'est le seul chemin vers `save_ecriture()`.

Cette séparation n'est pas de la prudence de principe : une écriture fausse ne se
voit pas dans un bilan, alors qu'une écriture manquante finit toujours par se
remarquer. Le coût des deux erreurs n'est pas symétrique, la conception non plus.
"""

from __future__ import annotations

import hashlib
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import date

from self_agri_book.storage import save_ecriture

from self_pa import storage
from self_pa.client import ClientPA, ErreurPlateforme
from self_pa.en_invoice import ErreurLectureEnInvoice, lire_en_invoice
from self_pa.imputation import JOURNAL_ACHATS, Gravite, analyser, proposer
from self_pa.models import CanalReception

log = logging.getLogger("selffarm.self_pa.reception")

SOURCE_MODULE = "self_pa"


@dataclass
class RapportReception:
    """Ce que la récupération a fait — de quoi l'afficher sans relire la base."""

    nouvelles: list[str] = field(default_factory=list)
    deja_connues: list[str] = field(default_factory=list)
    bloquees: list[str] = field(default_factory=list)
    echecs: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total_vues(self) -> int:
        return len(self.nouvelles) + len(self.deja_connues) + len(self.echecs)

    def resume(self) -> str:
        return (
            f"{len(self.nouvelles)} nouvelle(s), "
            f"{len(self.deja_connues)} déjà connue(s), "
            f"{len(self.bloquees)} à vérifier, "
            f"{len(self.echecs)} en échec"
        )


async def recuperer_nouvelles(client: ClientPA | None = None) -> RapportReception:
    """Récupère les factures reçues depuis la dernière fois.

    La reprise part du plus grand identifiant déjà enregistré : une facture
    traitée hier n'est pas retéléchargée aujourd'hui. Et même si elle l'était,
    la clé métier empêcherait le doublon — le curseur économise du réseau, il
    n'est pas ce qui garantit l'unicité.

    L'échec sur une facture n'interrompt pas les autres : une pièce jointe
    illisible chez un fournisseur ne doit pas priver l'exploitant des neuf
    autres factures du jour.
    """
    rapport = RapportReception()
    curseur = storage.dernier_id_plateforme()
    log.info("Réception : reprise après l'identifiant %s", curseur or "(aucun)")

    async with AsyncExitStack() as pile:
        pa = client or await pile.enter_async_context(ClientPA.depuis_env())
        async for resume_facture in pa.parcourir_recues(apres_id=curseur):
            identifiant = str(resume_facture.get("id", "?"))
            try:
                detail = await pa.obtenir_facture(identifiant)
                facture = lire_en_invoice(detail)

                # Le justificatif est téléchargé pour son empreinte : c'est elle
                # qui rattachera l'écriture à la pièce (`hash_pdf`). Un échec ici
                # ne doit pas perdre la facture, dont les données sont déjà lues.
                empreinte = None
                try:
                    pdf = await pa.telecharger_facture(identifiant)
                    empreinte = hashlib.sha256(pdf).hexdigest()
                except ErreurPlateforme as e:
                    log.warning("Facture %s : PDF indisponible (%s)", identifiant, e)

                imputation = analyser(facture)
                cle, creee = storage.enregistrer(
                    facture,
                    imputation,
                    canal=CanalReception.PLATEFORME,
                    provider_invoice_id=identifiant,
                    hash_fichier=empreinte,
                )
                if creee:
                    rapport.nouvelles.append(cle)
                    if not imputation.proposable:
                        rapport.bloquees.append(cle)
                else:
                    rapport.deja_connues.append(cle)

            except (ErreurPlateforme, ErreurLectureEnInvoice) as e:
                log.warning("Facture %s ignorée : %s", identifiant, e)
                rapport.echecs.append((identifiant, str(e)))

    log.info("Réception terminée — %s", rapport.resume())
    return rapport


def valider(cle_metier: str, compte_charge: str) -> int:
    """Comptabilise une facture reçue. Rend l'identifiant de l'écriture.

    Le seul point du module qui écrit en comptabilité, et il n'est atteint que
    sur décision d'un humain qui a choisi le compte de charge.

    Deux verrous se superposent, et c'est voulu : `marquer_validee()` refuse une
    facture déjà traitée, et `save_ecriture()` déduplique sur
    `(source_module, source_id)`. Le premier protège du double clic, le second
    d'un état incohérent entre les deux tables.
    """
    enregistree = storage.obtenir(cle_metier)
    if enregistree is None:
        raise ValueError(f"Facture {cle_metier!r} inconnue.")
    if enregistree["statut"] == "validee":
        raise ValueError(
            f"Facture {cle_metier!r} déjà comptabilisée "
            f"(écriture #{enregistree['ecriture_id']})."
        )

    facture = _relire(enregistree)
    imputation = proposer(facture, compte_charge)
    if not imputation.proposable:
        raise ValueError(
            f"Facture {cle_metier!r} : "
            + " ; ".join(a.message for a in imputation.anomalies if a.gravite is Gravite.BLOQUANT)
        )

    ligne = imputation.lignes[0]
    ecriture_id, creee = save_ecriture(
        date_operation=facture.date_facture or date.today(),
        journal=JOURNAL_ACHATS,
        numero_piece=facture.numero,
        libelle=ligne.libelle,
        compte_debit=ligne.compte_debit,
        compte_credit=ligne.compte_credit,
        montant_ttc=ligne.montant_ttc,
        montant_ht=ligne.montant_ht,
        montant_tva=ligne.montant_tva,
        source_module=SOURCE_MODULE,
        source_id=ligne.source_id,
        hash_pdf=enregistree.get("hash_fichier"),
    )
    if not storage.marquer_validee(cle_metier, ecriture_id):
        # L'écriture existe désormais, mais la facture n'a pas pu être marquée :
        # les deux tables sont en désaccord. Se taire ici laisserait la facture
        # réapparaître comme à traiter, avec une écriture déjà passée.
        raise RuntimeError(
            f"Écriture #{ecriture_id} créée pour {cle_metier!r}, mais la facture "
            "n'a pas pu être marquée validée — état à vérifier à la main."
        )
    log.info(
        "Facture %s comptabilisée → écriture #%d (%s)",
        cle_metier, ecriture_id, "créée" if creee else "déjà présente",
    )
    return ecriture_id


def _relire(enregistree: dict):
    """Reconstruit la `FactureRecue` telle qu'elle a été lue à la réception.

    On repart de l'objet sérialisé plutôt que des colonnes : la validation doit
    porter sur ce qui a été contrôlé, pas sur une reconstitution partielle qui
    pourrait diverger.
    """
    from self_pa.models import FactureRecue

    brut = enregistree.get("facture_json")
    if not brut:
        raise ValueError(
            f"Facture {enregistree['cle_metier']!r} : contenu d'origine absent."
        )
    return FactureRecue.model_validate_json(brut)
