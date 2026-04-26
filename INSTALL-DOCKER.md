# SelfFarm-Lite — Installation Docker (paysan lambda friendly)

> Tu n'as **rien à coder**. Juste 3 commandes copiées-collées et tu as ta compta agri local-first qui tourne.

---

## TL;DR (pour les pressés)

```bash
mkdir selffarm && cd selffarm
curl -O https://raw.githubusercontent.com/Pierroons/selffarm-lite/main/docker-compose.yml
docker compose up -d
```

→ Ouvre [http://localhost:8001](http://localhost:8001).
Tes données vivent dans le volume `selffarm-data` (sauvegardable, déplaçable, AGPL).

---

## 1. Installer Docker (une seule fois)

### Linux (Debian / Ubuntu / Mint)
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```
Reconnecte-toi pour que le groupe prenne effet.

### macOS / Windows
Télécharge **Docker Desktop** : https://www.docker.com/products/docker-desktop/
(Windows → active WSL2 quand il te le demande, c'est gratuit, c'est l'OS Linux dans Windows).

### Vérifier
```bash
docker run --rm hello-world
```
Si ça affiche "Hello from Docker!" → c'est bon.

---

## 2. Lancer SelfFarm-Lite

Dans n'importe quel dossier vide :

```bash
mkdir selffarm && cd selffarm
curl -O https://raw.githubusercontent.com/Pierroons/selffarm-lite/main/docker-compose.yml
docker compose up -d
```

Au bout de ~30 secondes (le temps de télécharger l'image, ~250 Mo), l'app est prête sur :

**http://localhost:8001**

### Ce qui est dispo dès le boot
- Hub compta avec écritures de démo
- Générateur Factur-X PDF/A-3
- Module DNJA prévisionnel
- Catalogue des aides JA
- Cartographie parcelles IGN multi-commune
- Export FEC DGFIP

---

## 3. Mises à jour

### Manuelle (recommandée pour rester maître du timing)
```bash
cd selffarm
docker compose pull
docker compose up -d
```

### Automatique (set-and-forget — Watchtower toutes les 6 h)
```bash
docker compose --profile auto-update up -d
```
Pour désactiver :
```bash
docker compose --profile auto-update down watchtower
```

### Comment SelfFarm versionne ses images

| Tag | Quand pull |
|-----|-----------|
| `latest` | Dernière version stable (branche `main`) |
| `dev` | Branche `develop` — tester avant la prod |
| `v0.4.0` | Version exacte figée — reproductibilité totale |
| `0.4` | Dernière patch de la minor 0.4 |

Pour épingler une version stricte, modifie `docker-compose.yml` :
```yaml
image: ghcr.io/pierroons/selffarm-lite:v0.4.0
```

---

## 4. Sauvegardes

**Toutes tes données sont dans le volume `selffarm-data`** (compta SQLite, factures émises, parcelles cartographiées, cache des aides).

### Backup
```bash
docker run --rm \
  -v selffarm-data:/data \
  -v $(pwd):/backup \
  busybox tar czvf /backup/selffarm-backup-$(date +%F).tar.gz -C / data
```

### Restore
```bash
docker compose down
docker run --rm \
  -v selffarm-data:/data \
  -v $(pwd):/backup \
  busybox tar xzvf /backup/selffarm-backup-2026-04-24.tar.gz -C /
docker compose up -d
```

### Migration vers un autre PC
1. Backup sur l'ancien (cf. ci-dessus).
2. Copie le `.tar.gz` sur le nouveau.
3. Installe Docker + docker-compose.yml sur le nouveau.
4. Restore (cf. ci-dessus).
5. C'est tout.

---

## 5. Diagnostic

### Voir les logs en direct
```bash
docker compose logs -f selffarm
```

### Vérifier que ça tourne
```bash
docker compose ps
curl http://localhost:8001/healthz
```
Attendu : `{"status":"ok","version":"0.x.x","env":"prod"}`

### Redémarrer
```bash
docker compose restart selffarm
```

### Tout arrêter (sans perdre les données)
```bash
docker compose down
```

### Tout supprimer (⚠ y compris les données)
```bash
docker compose down -v
```

---

## 6. Aller plus loin

### Exposer sur le LAN
Édite `docker-compose.yml`, change la ligne :
```yaml
    ports:
      - "8001:8001"
```
en :
```yaml
    ports:
      - "0.0.0.0:8001:8001"
```
Puis depuis un autre poste : `http://IP-DU-PC-HOTE:8001`.

### Reverse proxy HTTPS (Caddy / nginx)
Cf. `docs/deploy-reverse-proxy.md` (à venir).

### Lancer la CLI (export FEC, calcul DNJA, etc.)
```bash
docker compose exec selffarm python -m self_dnja.cli --help
docker compose exec selffarm python -m self_aid.cli list-aides
```

---

## Questions fréquentes

**Q : Docker, c'est lourd ?**
R : ~250 Mo l'image + 80 Mo de RAM en idle. Tourne nickel sur un PC fixe, un mini-PC, un Raspberry Pi 4 (l'image est multi-arch amd64+arm64).

**Q : Mes données partent dans le cloud ?**
R : **Non.** Tout est local dans `selffarm-data`. Aucune télémétrie, aucune connexion sortante hors mises à jour Docker que tu déclenches.

**Q : Je peux passer à une autre version puis revenir en arrière ?**
R : Oui, change le tag dans `docker-compose.yml` (`v0.3.0` → `v0.4.0` ou inverse) puis `docker compose up -d`. Le volume reste compatible.

**Q : Et si le format compta change ?**
R : Les migrations SQLite tournent au boot. Pour les ruptures majeures (rares), une note est ajoutée dans le `CHANGELOG.md` avec la marche à suivre.

**Q : C'est vraiment AGPL ?**
R : Oui. Code source : https://github.com/Pierroons/selffarm-lite — tu peux fork, modifier, redistribuer (sous AGPL, contrib bienvenues).

---

## Support

- Bugs / questions : https://github.com/Pierroons/selffarm-lite/issues
- Site projet : https://selffarm.my-self.fr
- Écosystème global : https://my-self.fr
