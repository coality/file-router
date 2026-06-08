# FileRouter — Document d'exploitation

> Guide opérationnel consolidé pour l'équipe d'exploitation/support. Complète
> [13-operations-guide](13-operations-guide.md) et [12-deployment](12-deployment.md).

## 1. Installation

### Bundle portable Windows (recommandé, sans rien installer)
Décompresser l'archive, puis (une seule fois) créer sa config depuis le modèle :
```powershell
copy config\config.example.yaml config\config.yaml
filerouter-doctor.bat --config config\config.yaml --fix --yes
filerouter.bat        --config config\config.yaml validate-config
filerouter.bat        --config config\config.yaml run
```
Python ET GnuPG sont embarqués. Compatible Windows 10/11 et Server 2016→2025 (x64).

### Depuis les sources (venv)
`pip install ".[windows]"` (Windows) ou `pip install "."` (Linux) ; ajouter
`gnupg`/`pgpy` selon le backend de chiffrement.

## 2. Configuration

- `base_folders` (alias → chemin), `exchange`, `runtime`, `naming`, `hashing`.
- `inclusion`/`exclusion` : globs **insensibles à la casse**, identiques Linux/Windows.
  Filtrer par extension : `inclusion: { patterns: ["*.csv", "*.xml"] }`.
  Ignorer un répertoire : `exclusion: { patterns: ["archive/**", "*/archive/*"] }`.
- **Chiffrement** :
  - `backend: pgpy` → `private_key_file`, `public_key_file`, `passphrase_file` (chemins ; ACL au compte de service) ;
  - `backend: gnupg` → `gnupg_home`, `signing_key_id`, `recipient_key_ids`, passphrase via env/fichier.
- **Toujours valider** : `filerouter ... validate-config`. **Diagnostiquer** :
  `filerouter-doctor`.

## 3. Commandes CLI

| Commande | Usage |
|----------|-------|
| `validate-config` | Valide la config sans démarrer |
| `health` | Self-test (config, crypto) |
| `preview [--watched-only]` | Lecture seule : fichiers surveillés/ignorés (+ raison) et paires entrantes |
| `history [--limit N]` | Journal de transferts lisible (support) |
| `trace <technical_id>` | Historique audit corrélé d'un fichier |
| `list-quarantine` | Items en `runtime/error/` |
| `reconcile` | Réconciliation immédiate (reprise) |
| `run` | Boucle de service en avant-plan |
| `doctor [--fix] [--yes]` | Diagnostic config/environnement |

## 4. Exécution en service

### Windows (sous compte de service — recommandé pour UNC)
```powershell
filerouter-service.bat install --config "%CD%\config\config.yaml" ^
    --username "DOMAINE\svc_filerouter" --password "***" --startup auto
filerouter-service.bat start
```
Multi-instances : `... install --instance siteA --config <…>` crée `FileRouter_siteA`.
Le compte doit avoir « Ouvrir une session en tant que service » et l'accès aux
répertoires métier/échange/runtime (et au trousseau/secret).

### Linux (systemd)
Voir le modèle d'unité dans [12-deployment](12-deployment.md#4-linux--systemd).

## 5. Supervision

- **Santé** : `health` (code de retour pour sonde).
- **Backlog/quarantaine** : surveiller `runtime/error/` (objectif : 0) ;
  `list-quarantine` puis lire `runtime/error/<id>/error.json`.
- **Historique support** : `history` ou ouvrir `logs/transfers.log` (date, sens,
  noms, flags chiffré/signé/compressé, SHA-256, chemins).
- **Logs structurés** : flux JSON-Lines sous `logs/` (projetables vers un SIEM).

## 6. Gros fichiers en cours de copie

FileRouter ne traite un fichier que lorsqu'il est **stable** (taille+mtime
inchangés sur `stability_checks` relevés espacés de `stability_interval_seconds`,
+ ouverture exclusive sous Windows). Pour de très gros fichiers/transports lents,
augmenter ces deux valeurs. **Bonne pratique producteur** : écrire en `.tmp`/`.part`
puis renommer (exclu par défaut) → le fichier n'apparaît que complet.

## 7. Mise à jour en place (sans casser, sans écraser la config)

1. Arrêter le service (`filerouter-service.bat stop`), et si gnupg embarqué était
   utilisé, arrêter l'agent (`gpgconf --kill all`).
2. Décompresser la nouvelle archive dans le **même dossier `filerouter\`** : le
   programme est remplacé ; **`config.yaml` n'est jamais écrasé** (l'archive ne
   contient que `config.example.yaml`).
3. Redémarrer le service.
Garder `runtime`/`exchange`/trousseau/secret **hors** du dossier du bundle.

## 8. Sauvegarde & reprise après incident

- L'état vit sur le FS : sauvegarder `runtime/` (audit, dedup, quarantaine),
  la config et le trousseau/secret. Pas de base de données à sauvegarder.
- Au redémarrage, `reconcile` rejoue la reprise (opérations idempotentes).

## 9. Dépannage rapide

| Symptôme | Piste |
|----------|-------|
| Le service ne démarre pas | `validate-config` ; droits du compte ; accès au config (`FILEROUTER_CONFIG_<INSTANCE>`) |
| Rien n'est routé | `preview` (règles d'inclusion/exclusion) ; stabilité ; rôle de l'instance |
| Fichier en quarantaine | `runtime/error/<id>/error.json` ; hash/signature/clé |
| Chiffrement KO | `health` ; présence des clés ; passphrase (env/fichier) ; backend |
| Accès UNC refusé (service) | utiliser un **compte de service de domaine** (pas LocalSystem) |
