# FileRouter — Document d'architecture

> Vue d'ensemble technique consolidée. Pour le détail par sujet, voir les
> chapitres numérotés `00`–`18` de ce dossier.

## 1. Objectif et principes

FileRouter est un **routeur de fichiers d'entreprise, local, sans réseau et sans
base de données**. Il détecte des fichiers dans des répertoires métier, calcule
leurs empreintes, les compresse/chiffre/signe éventuellement, les renomme et les
dépose dans des répertoires d'échange plats. À la réception, il valide, déchiffre,
reconstruit l'arborescence métier et livre.

Principes directeurs :

- **Zéro base de données** : le **système de fichiers est l'unique source de
  vérité**. Aucune dépendance externe à installer/sauvegarder/sécuriser.
- **Aucun transport réseau** : le transfert inter-sites est externe (MFT,
  réplication, partage) — hors périmètre.
- **Atomicité + idempotence** : opérations atomiques (rename intra-volume), reprise
  sur incident sans perte ni double publication.
- **Audit reconstructible** par fichier + journal de transferts lisible.
- **Multi-plateforme** : cœur portable, service Windows natif (pywin32) et systemd.

## 2. Architecture hexagonale

| Couche | Contenu |
|--------|---------|
| `core/` | Domaine pur (pipelines, règles, hachage, chemins, état). Aucune I/O concrète. |
| `ports/` | Interfaces : `FileStore`, `CryptoProvider`, `Clock`, `IdGenerator`, `LockManager`, `LogSink`. |
| `adapters/` | Implémentations : FS local, GnuPG/PGPy/noop, ULID, verrous fichier, JSONL. |
| `config/` | Modèle typé + chargement YAML (`safe_load`) + validation JSON Schema. |
| `cli/`, `service/` | Entrées : CLI, service Windows / systemd, composition (`runner`). |

Le **`Context`** (dataclass gelée) regroupe tous les ports câblés une seule fois
au démarrage (`service/runner.py:build_context`), si bien que chaque méthode des
processeurs reste minuscule.

## 3. Flux sortant (business → `exchange_out`)

`core/outbound.py`, pipeline transactionnel (toute erreur → quarantaine, source
jamais perdue) :

1. détecter (stabilité requise, cf. §6) ;
2. verrou sur la source ;
3. déplacer vers `processing/<id>/clear` ;
4. hash SHA-256 du clair ;
5. déduplication (politique configurable) ;
6. **compresser (gzip) PUIS chiffrer (OpenPGP)** selon les règles ;
7. hash du payload ;
8. nom technique (`naming`) ;
9. **publier** : payload → (signature metadata détachée) → metadata (ordre garanti) ;
10. archiver/supprimer la source ; journaliser le transfert.

## 4. Flux entrant (`exchange_in` → business)

`core/inbound.py`, ordre de validation strict :

1. **readiness sans DB** : présence de la paire (payload + metadata, + `.sig` si
   l'émetteur a signé), stabilité, âge (mtime) — survit aux redémarrages ;
2. déplacer la paire dans `processing/<id>/` ;
3. **vérifier le hash du payload AVANT toute crypto** (anti-corruption) ;
4. **vérifier la signature détachée de la metadata** (authentifie le routage) ;
5. déchiffrer + **vérifier la signature du contenu** et le **signataire autorisé** ;
6. décompresser ;
7. **vérifier le hash du clair** (intégrité bout-en-bout) ;
8. reconstruire le chemin métier (alias → chemin local + `relative_path` +
   `original_filename`) et livrer atomiquement ; journaliser.

## 5. Modèle d'état, quarantaine, reprise

- L'état d'un fichier est **implicite** : sa position + sa trace d'audit.
- Toute erreur → `runtime/error/<id>/` avec `error.json` ; jamais de livraison « au doute ».
- `reconcile` (au démarrage et périodique) nettoie `processing/` orphelin, ré-arme
  les items récupérables — idempotent.
- Déduplication : marqueurs `O_EXCL` par hash sous `runtime/dedup/`.

## 6. Stabilité (fichiers en cours de copie)

`LocalFileStore.is_stable` combine **quiescence** (taille + mtime inchangés sur N
relevés espacés de `stability_interval_seconds`) et **ouverture exclusive** (sous
Windows, échoue tant qu'un writer tient le fichier). Recommandation producteur :
écrire en `.tmp`/`.part` puis renommer (exclusions par défaut). Voir
[13-operations-guide](13-operations-guide.md).

## 7. Cryptographie

Trois backends derrière `CryptoProvider` :

- **`noop`** : pas de chiffrement (passthrough).
- **`pgpy`** : pur Python, **clés sur fichiers** (`private_key_file`,
  `public_key_file`, `passphrase_file`) — aucun trousseau à gérer.
- **`gnupg`** : via `gpg` (trousseau `gnupg_home` + key IDs).

Le contenu est **chiffré ET signé** ; la **metadata est signée séparément**
(signature détachée) pour authentifier les champs de routage. La passphrase de la
clé privée vient de l'environnement ou d'un **fichier à ACL restreinte**, jamais du YAML.

## 8. Formats, audit, journal

- **Nom technique** : motif configurable (`{flow}_{direction}_{timestamp}_{technical_id}.{ext}`),
  jeu de caractères portable, noms Windows réservés gérés.
- **Metadata** (`*.meta.json`) : tout pour reconstruire et auditer + hashes clair/payload.
- **Audit** : événements JSON-Lines par `technical_id` (corrélation metadata ↔ audit ↔ logs).
- **Journal de transferts** (`logs/transfers.log`) : une ligne lisible par transfert
  (date, sens, noms, flags clair/chiffré/signé/compressé, SHA-256, chemins) — pour le support.

## 9. Concurrence et portabilité

- Coordination **uniquement par verrous fichier** → fonctionne en threads,
  process, ou multi-hôtes partageant le stockage (UNC supporté ; garder
  `runtime`/`exchange` sur le même partage pour des renames atomiques).
- **Service Windows natif** (pywin32, multi-instances, sous compte de service) et
  **systemd** Linux. Le cœur est identique sur les deux OS (matching de chemins
  insensible à la casse, normalisé POSIX).

## 10. Distribution

- Wheel Python + venv, OU **bundle portable Windows** 100 % autonome (Python +
  dépendances + GnuPG embarqués) — voir [12-deployment](12-deployment.md) et le
  README. Mise à jour en place sans écraser la configuration.
