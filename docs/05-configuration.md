# 05 — Configuration

Toute la configuration est externalisée au format **YAML**. **Aucun paramètre métier n'est
codé en dur.** Le fichier est validé au démarrage contre
[`schemas/config.schema.json`](schemas/config.schema.json) ; une config invalide interrompt
le démarrage (fail-fast). Un exemple complet figure dans
[`examples/config.example.yaml`](examples/config.example.yaml).

## 1. Sections configurables (vue d'ensemble)

| Section | Rôle |
|---------|------|
| `instance` | Identité de l'hôte (site, rôle), seuils de concurrence. |
| `base_folders` | Racines métier (alias + chemin local). |
| `mappings` | Tables alias↔site/flow, mapping inter-serveur. |
| `exchange` | Chemins `exchange_in` / `exchange_out`. |
| `runtime` | Emplacement de l'arborescence `runtime/`. |
| `naming` | Convention de nommage technique. |
| `hashing` | Algorithme (SHA-256) et options de vérification. |
| `encryption` | Backend OpenPGP, trousseaux, règles de chiffrement. |
| `inclusion` / `exclusion` | Règles glob d'éligibilité des fichiers. |
| `archival` | Politique d'archivage des sources sortantes. |
| `retention` | Rétention de `archive/`, `audit/`, `logs/`. |
| `scanning` | Fréquence de scan, stabilité, grâce d'appariement. |
| `locking` | TTL de verrou, intervalle de heartbeat. |
| `logging` | Flux de logs, niveaux, rotation, compression. |
| `recovery` | Paramètres de réconciliation/reprise. |

## 2. Détail des sections

### 2.1 `instance`
```yaml
instance:
  site: PARIS            # source_site par défaut pour les fichiers produits ici
  role: both             # outbound | inbound | both
  workers: 8             # taille du pool de workers
  worker_type: thread    # thread | process
```

### 2.2 `base_folders`
Nombre **illimité** de racines, chaque fichier appartenant à exactement une.
```yaml
base_folders:
  - alias: SAP_FR
    path: D:\interfaces\sap\fr
  - alias: CRM_DE
    path: E:\interfaces\crm\de
  - alias: PAYMENT
    path: F:\payments
```
> Sur un autre serveur, l'**alias reste identique** mais le `path` diffère — c'est le
> mécanisme de mapping inter-serveur. Voir [00 §4](00-overview.md).

### 2.3 `mappings`
```yaml
mappings:
  flows:                 # alias → libellé de flux pour {flow} dans le nommage
    PAYMENT: PAYMENT
    SAP_FR: SAPFR
  routing:               # alias → site cible (renseigne target_site)
    PAYMENT: FRANKFURT
    SAP_FR: PARIS
```

### 2.4 `exchange` & `runtime`
```yaml
exchange:
  out: D:\FileRouter\exchange_out   # plat, aucune sous-arbo
  in:  D:\FileRouter\exchange_in    # plat, aucune sous-arbo
runtime:
  root: D:\FileRouter\runtime       # même volume que exchange (publication atomique)
```

### 2.5 `naming`
```yaml
naming:
  pattern: "{flow}_{direction}_{timestamp}_{technical_id}.{extension}"
  timestamp_format: "%Y%m%dT%H%M%S"
  max_length: 120
  technical_id_strategy: ulid
  charset: portable
  meta_suffix: ".meta.json"   # appliqué au nom technique complet
```

### 2.6 `hashing`
```yaml
hashing:
  algorithm: SHA-256       # imposé
  chunk_size_bytes: 1048576
  verify_inbound: true     # rejeu des vérifications payload puis clair
```

### 2.7 `encryption`
```yaml
encryption:
  backend: gnupg           # gnupg | pgpy
  gnupg_home: D:\FileRouter\keys\gnupg
  signing_key_id: "0xCAFEBABE"
  require_signature_inbound: true
  rules:
    - base_folder_alias: SAP_FR
      path_pattern: "confidential/**"
      enabled: true
      recipient_key_ids: ["0xDEADBEEF"]
    - base_folder_alias: PAYMENT
      path_pattern: "**"
      enabled: true
      recipient_key_ids: ["0xDEADBEEF"]
```
Détails du modèle de clés, rotation et signature : [06 — Chiffrement](06-encryption.md).

### 2.8 `inclusion` / `exclusion`
```yaml
inclusion:
  patterns: ["**/*"]            # éligibles par défaut
exclusion:
  patterns:
    - "**/*.tmp"
    - "**/*.part"
    - "**/~$*"                  # fichiers temporaires Office
    - "**/.DS_Store"
```
> L'exclusion l'emporte sur l'inclusion. Les fichiers d'échange (`*.meta.json`) sont
> implicitement gérés et ne sont jamais traités comme des sources métier.

### 2.9 `archival` & `retention`
```yaml
archival:
  source_policy: archive        # archive | delete
  archive_layout: "%Y/%m/%d"    # sous-arbo de runtime/archive
retention:
  archive_days: 30
  audit_days: 365
  logs_days: 90
  error_days: 0                 # 0 = jamais auto-supprimé (action opérateur requise)
```

### 2.10 `scanning` & `locking`
```yaml
scanning:
  interval_seconds: 5
  stability_checks: 3
  stability_interval_seconds: 2
  pair_grace_period_seconds: 30
locking:
  lock_ttl_seconds: 300
  heartbeat_interval_seconds: 30
```

### 2.11 `logging`
```yaml
logging:
  format: jsonl
  streams:
    technical:  { level: INFO,    path: logs/technical }
    functional: { level: INFO,    path: logs/functional }
    security:   { level: INFO,    path: logs/security }
    admin:      { level: INFO,    path: logs/admin }
  rotation:
    when: daily            # daily | size
    max_bytes: 104857600   # si when=size
    backup_count: 30
  compression: gzip        # none | gzip
```

### 2.12 `recovery`
```yaml
recovery:
  reconcile_on_start: true
  reconcile_interval_seconds: 300
  temp_orphan_max_age_seconds: 600
```

## 3. Validation & rechargement
- **Validation au démarrage** contre le JSON Schema + contrôles sémantiques (alias uniques,
  motif de nommage contenant `{technical_id}`, chemins existants, `runtime`/`exchange` sur le
  même volume, clés de chiffrement présentes dans le trousseau).
- **Rechargement** : un signal d'administration (`SIGHUP` sous Linux, commande de contrôle de
  service sous Windows) déclenche une revalidation puis un swap atomique de la config en
  mémoire. Une config invalide est **rejetée** et l'ancienne reste active (jamais de
  démarrage/rechargement sur une config cassée).
