# 04 — Formats de données

Ce document définit la **convention de nommage**, la structure complète du **metadata JSON**
et celle du **fichier d'audit JSON**. Les schémas vérifiables par machine se trouvent dans
[`schemas/`](schemas/) et des instances de référence dans [`examples/`](examples/).

## 1. Convention de nommage

Le nom technique utilisé dans les répertoires d'échange est entièrement configurable via un
motif à placeholders (voir [05 — Configuration](05-configuration.md)).

```yaml
naming:
  pattern: "{flow}_{direction}_{timestamp}_{technical_id}.{extension}"
  timestamp_format: "%Y%m%dT%H%M%S"
  max_length: 120
  technical_id_strategy: ulid   # ulid | uuid4
  charset: portable             # A-Z a-z 0-9 _ - . uniquement
```

### Catalogue de placeholders

| Placeholder | Source | Exemple |
|-------------|--------|---------|
| `{flow}` | alias du base_folder (ou `flow` dérivé d'un mapping) | `PAYMENT` |
| `{direction}` | `OUT` (sortant) / `IN` (entrant) | `OUT` |
| `{timestamp}` | horloge à la détection, format `timestamp_format` | `20260608T120000` |
| `{technical_id}` | identifiant unique (ULID/UUIDv4) | `ABC123` |
| `{extension}` | extension d'origine, sans le point | `csv` |
| `{base_folder_alias}` | alias brut | `PAYMENT` |
| `{source_site}` / `{target_site}` | sites issus de la config | `PARIS` |

### Contraintes
- **Lisible pour le support** ; longueur **maîtrisée** via `max_length` (le rendu est rejeté,
  audité `ERROR`, et l'item est mis en quarantaine si le nom dépasse).
- **Indépendant de l'arborescence métier** : le chemin métier n'apparaît jamais dans le nom ;
  il est porté par la metadata.
- **Identifiant unique obligatoire** : `{technical_id}` est requis dans tout motif (validé au
  démarrage).
- **Portabilité** : `charset: portable` interdit les caractères problématiques sur Windows
  (`< > : " / \ | ? *`), les espaces et les noms réservés (`CON`, `PRN`, `AUX`, `NUL`, …).
- **Réversibilité** : le nom d'origine n'est pas dérivé du nom technique ; il est restauré
  depuis `original_filename` dans la metadata. Le nom technique peut donc être purement
  opaque sans perte d'information.

### Appariement payload / metadata
Le payload et sa metadata partagent le même radical, la metadata ajoutant `.meta.json` :

```text
PAYMENT_OUT_20260608T120000_ABC123.csv
PAYMENT_OUT_20260608T120000_ABC123.csv.meta.json
```

> Variante acceptée par le schéma : `..._ABC123.meta.json` (sans répéter l'extension du
> payload). Le format effectif est fixé par `naming.meta_suffix` dans la config. La paire est
> toujours co-localisée et déplacée atomiquement ensemble.

## 2. Structure du metadata JSON

Le metadata est un sur-ensemble des champs minimaux requis. Schéma :
[`schemas/metadata.schema.json`](schemas/metadata.schema.json).

```json
{
  "schema_version": "1.0",
  "technical_id": "ABC123",
  "direction": "OUT",
  "source_site": "PARIS",
  "target_site": "FRANKFURT",
  "base_folder_alias": "PAYMENT",
  "relative_path": "clients/contracts/v5/production/2026/06/exports/batch01",
  "original_filename": "file.csv",
  "technical_filename": "PAYMENT_OUT_20260608T120000_ABC123.csv",
  "extension": "csv",
  "encrypted": true,
  "size_bytes": 184320,
  "clear_file_hash":   { "algorithm": "SHA-256", "value": "…64 hex…" },
  "payload_file_hash": { "algorithm": "SHA-256", "value": "…64 hex…" },
  "encryption": {
    "scheme": "OpenPGP",
    "recipient_key_ids": ["0xDEADBEEF"],
    "signing_key_id": "0xCAFEBABE",
    "signed": true,
    "key_epoch": "2026-Q2"
  },
  "naming": {
    "pattern": "{flow}_{direction}_{timestamp}_{technical_id}.{extension}",
    "timestamp": "20260608T120000"
  },
  "creation_date": "2026-06-08T12:00:00Z",
  "producer": { "app": "FileRouter", "version": "1.0.0", "host": "SRV-A" }
}
```

### Champs requis (minimum imposé)
`technical_id`, `source_site`, `target_site`, `base_folder_alias`, `relative_path`,
`original_filename`, `encrypted`, `creation_date`, plus `clear_file_hash` et
`payload_file_hash` (imposés par la section [07 — Empreintes](07-hashing.md)).

### Règles
- `relative_path` est **normalisé POSIX** (séparateurs `/`), sans `.`/`..`, jamais absolu —
  garantissant un transport sûr entre Windows et Linux.
- `encryption` est requis si `encrypted == true`, interdit sinon.
- Quand `encrypted == false`, `payload_file_hash == clear_file_hash` (le payload est le clair).
- `creation_date` est en **UTC ISO-8601** (`Z`).

## 3. Structure du fichier d'audit JSON

L'audit est en **JSON-Lines append-only** : une ligne JSON par événement, jamais réécrite.
Fichier : `runtime/audit/<technical_id>.audit.json`. Schéma :
[`schemas/audit.schema.json`](schemas/audit.schema.json).

```json
{"technical_id":"ABC123","seq":1,"event":"DETECTED","ts":"2026-06-08T12:00:00.001Z","direction":"OUT","host":"SRV-A","actor":"OutboundProcessor","details":{"source_abspath":"D:\\interfaces\\...\\file.csv","base_folder_alias":"PAYMENT"}}
{"technical_id":"ABC123","seq":2,"event":"HASH_COMPUTED","ts":"2026-06-08T12:00:00.120Z","host":"SRV-A","details":{"target":"clear","algorithm":"SHA-256","value":"…"}}
{"technical_id":"ABC123","seq":3,"event":"ENCRYPTED","ts":"2026-06-08T12:00:00.480Z","host":"SRV-A","details":{"recipient_key_ids":["0xDEADBEEF"],"signing_key_id":"0xCAFEBABE"}}
{"technical_id":"ABC123","seq":4,"event":"HASH_COMPUTED","ts":"2026-06-08T12:00:00.500Z","host":"SRV-A","details":{"target":"payload","algorithm":"SHA-256","value":"…"}}
{"technical_id":"ABC123","seq":5,"event":"RENAMED","ts":"2026-06-08T12:00:00.520Z","host":"SRV-A","details":{"technical_filename":"PAYMENT_OUT_20260608T120000_ABC123.csv"}}
{"technical_id":"ABC123","seq":6,"event":"MOVED_TO_EXCHANGE_OUT","ts":"2026-06-08T12:00:00.560Z","host":"SRV-A","details":{"path":"D:\\FileRouter\\exchange_out\\PAYMENT_OUT_20260608T120000_ABC123.csv"}}
{"technical_id":"ABC123","seq":7,"event":"ARCHIVED","ts":"2026-06-08T12:00:00.600Z","host":"SRV-A","details":{"archive_path":"runtime/archive/2026/06/08/ABC123__file.csv"}}
```

### Champs d'un événement
| Champ | Type | Description |
|-------|------|-------------|
| `technical_id` | string | Corrélation (identique au nom de fichier). |
| `seq` | int | Numéro de séquence monotone par fichier (détecte les trous). |
| `event` | enum | Voir le vocabulaire ci-dessous. |
| `ts` | string | UTC ISO-8601 avec millisecondes. |
| `direction` | enum | `OUT` / `IN` (sur le premier événement au minimum). |
| `host` | string | Hôte ayant produit l'événement. |
| `actor` | string | Composant émetteur. |
| `details` | object | Charge spécifique à l'événement. |

### Vocabulaire d'événements (exhaustif et minimal)
`DETECTED`, `HASH_COMPUTED`, `ENCRYPTED`, `RENAMED`, `MOVED_TO_EXCHANGE_OUT`,
`RECEIVED_FROM_EXCHANGE_IN`, `HASH_VALIDATED`, `DECRYPTED`, `RESTORED`,
`MOVED_TO_BUSINESS_FOLDER`, `ARCHIVED`, `ERROR`.

Un événement `ERROR` porte `details.step`, `details.exception_type`, `details.message` et
`details.quarantine_path`. Tout `ERROR` est **terminal** pour le pipeline courant tant que
l'opérateur n'a pas rejoué l'item.

### Reconstructibilité
L'**historique complet** d'un fichier se reconstruit en relisant son `*.audit.json` dans
l'ordre des `seq`. La présence d'un événement terminal (`MOVED_TO_*` ou `ARCHIVED` côté
succès, `ERROR` côté échec) indique l'état final ; l'absence indique un traitement interrompu
que la réconciliation prendra en charge.
