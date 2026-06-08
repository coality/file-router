# 17 — Structure du projet Python

## 1. Arborescence complète

```text
file-router/
├── pyproject.toml                 # packaging, métadonnées, deps, outils
├── requirements.lock              # dépendances figées
├── README.md
├── LICENSE
├── docs/                          # cette spécification
├── config/
│   └── config.example.yaml        # config de référence
├── src/
│   └── filerouter/
│       ├── __init__.py
│       ├── __main__.py            # point d'entrée CLI (python -m filerouter)
│       ├── version.py             # __version__, SCHEMA_VERSIONS
│       │
│       ├── core/                  # cœur portable (aucune dépendance OS/crypto directe)
│       │   ├── __init__.py
│       │   ├── orchestrator.py    # boucle de scan, pool de workers, shutdown coopératif
│       │   ├── outbound.py        # OutboundProcessor (pipeline 10 étapes)
│       │   ├── inbound.py         # InboundProcessor (pipeline 8 étapes)
│       │   ├── state_machine.py   # transitions légales + opérations atomiques
│       │   ├── naming.py          # moteur de nommage + mapping inverse
│       │   ├── hashing.py         # SHA-256 en flux, comparaison sûre
│       │   ├── metadata.py        # modèle, sérialisation, validation
│       │   ├── audit.py           # écriture/lecture JSON-Lines, reconstruction
│       │   ├── reconciliation.py  # réconciliation/reprise au démarrage
│       │   ├── dedup.py           # index de doublons sur FS
│       │   ├── rules.py           # inclusion/exclusion, matching de règles de chiffrement
│       │   ├── pathing.py         # base_folder match, relative_path POSIX
│       │   ├── retention.py       # purge archive/audit/logs
│       │   ├── errors.py          # taxonomie d'exceptions
│       │   └── models.py          # dataclasses (FileItem, KeyInfo, VerificationResult…)
│       │
│       ├── ports/                 # interfaces (Protocol/ABC) — contrats du cœur
│       │   ├── __init__.py
│       │   ├── file_store.py      # FileStore
│       │   ├── lock_manager.py    # LockManager
│       │   ├── crypto_provider.py # CryptoProvider
│       │   ├── clock.py           # Clock
│       │   ├── log_sink.py        # LogSink
│       │   └── id_generator.py    # IdGenerator
│       │
│       ├── adapters/              # implémentations concrètes des ports
│       │   ├── __init__.py
│       │   ├── local_file_store.py     # os/pathlib, atomicité, cross-volume, stabilité
│       │   ├── file_lock_manager.py    # O_EXCL + heartbeat + reaper
│       │   ├── gnupg_provider.py       # backend GnuPG (python-gnupg)
│       │   ├── pgpy_provider.py        # backend PGPy (python pur)
│       │   ├── system_clock.py
│       │   ├── jsonl_log_sink.py       # 4 flux, rotation, compression, async
│       │   └── ulid_generator.py
│       │
│       ├── config/                # configuration
│       │   ├── __init__.py
│       │   ├── loader.py          # chargement YAML (safe_load)
│       │   ├── schema.py          # validation jsonschema + contrôles sémantiques
│       │   └── model.py           # dataclasses de config typées
│       │
│       ├── service/               # enveloppes de service (seul code spécifique OS)
│       │   ├── __init__.py
│       │   ├── runner.py          # démarrage/arrêt portable de l'orchestrateur
│       │   ├── windows.py         # service pywin32 (install/start/stop/run)
│       │   └── linux.py           # daemon systemd (Type=notify, watchdog)
│       │
│       ├── cli/                   # commandes d'administration
│       │   ├── __init__.py
│       │   └── commands.py        # status, health, trace, replay, reconcile, reload, keys…
│       │
│       └── observability/
│           ├── __init__.py
│           ├── metrics.py         # collecte + export (textfile/json)
│           └── health.py          # self-test, health.json
│
├── schemas/                       # JSON Schemas (référencés par docs/schemas)
│   ├── metadata.schema.json
│   ├── audit.schema.json
│   └── config.schema.json
│
└── tests/                         # voir 18-testing-strategy.md
    ├── unit/
    ├── integration/
    ├── load/
    ├── security/
    ├── recovery/
    ├── regression/
    ├── fs_robustness/
    ├── fixtures/
    └── conftest.py
```

## 2. Description des modules

### `core/` (portable)

| Module | Responsabilité |
|--------|----------------|
| `orchestrator.py` | Boucle de scan (`scan_interval`), énumération outbound/inbound avec règles, dispatch au pool de workers borné, arrêt coopératif, déclenchement de la réconciliation. |
| `outbound.py` | Pipeline sortant en 10 étapes ; chaque étape idempotente, émet un audit, fait avancer la machine à états. |
| `inbound.py` | Pipeline entrant en 8 étapes ; ordre de validation strict (payload-hash → sig+déchiffrement → clair-hash → déplacement). |
| `state_machine.py` | Définit les transitions légales et expose les opérations atomiques (move/publish via FileStore). Autorité unique sur l'état. |
| `naming.py` | Rend le nom technique depuis le motif, applique `max_length`/charset, génère `technical_id`, restaure le nom d'origine depuis la metadata. |
| `hashing.py` | SHA-256 en streaming (mémoire constante), comparaison à temps constant. |
| `metadata.py` | Construit/sérialise/valide la metadata ; garantit les invariants (encrypted⇒encryption, relative_path POSIX). |
| `audit.py` | Écrit les événements JSON-Lines (temp+rename pour le fichier, append pour les lignes), reconstruit l'historique, fournit le dernier état. |
| `reconciliation.py` | Classe et traite les orphelins (`temp/`, `processing/`, `staging/`, `locks/`, échange), relance/finalise/quarantaine. |
| `dedup.py` | Index de doublons sur FS (marqueurs `O_EXCL` par hash) ; politiques skip/overwrite/error. |
| `rules.py` | Compile et évalue inclusion/exclusion (glob) et règles de chiffrement (alias + path_pattern). |
| `pathing.py` | Identifie le base_folder par plus long préfixe ; calcule `relative_path` normalisé POSIX ; reconstruit `base_path / relative_path`. |
| `retention.py` | Balayage de purge idempotent/interruptible pour archive/audit/logs/dedup. |
| `errors.py` | Hiérarchie d'exceptions typées (Transient, Integrity, Crypto, Config, Data). |
| `models.py` | Dataclasses du domaine (FileItem, Metadata, AuditEvent, KeyInfo, VerificationResult). |

### `ports/` & `adapters/`

| Port | Adaptateur(s) | Notes |
|------|---------------|-------|
| `FileStore` | `local_file_store.py` | `os.replace`, copie cross-volume+fsync, énumération, contrôle de taille stable, sonde d'ouverture exclusive (Windows). |
| `LockManager` | `file_lock_manager.py` | Verrou `O_EXCL`, heartbeat, détection/réclamation de périmé. |
| `CryptoProvider` | `gnupg_provider.py`, `pgpy_provider.py` | encrypt/decrypt/sign/verify/list_keys ; self-test au boot. |
| `Clock` | `system_clock.py` | temps monotone + UTC ; injectable pour tests (horloge figée). |
| `LogSink` | `jsonl_log_sink.py` | 4 flux JSON-Lines, rotation/compression, écriture asynchrone non bloquante. |
| `IdGenerator` | `ulid_generator.py` | `technical_id` ULID (ordonnable) ou UUIDv4. |

### `config/`, `service/`, `cli/`, `observability/`

| Module | Responsabilité |
|--------|----------------|
| `config/loader.py` | Chargement YAML sûr (`yaml.safe_load`). |
| `config/schema.py` | Validation `jsonschema` + contrôles sémantiques (alias uniques, même volume runtime/exchange, motif contient `{technical_id}`, clés présentes). |
| `config/model.py` | Représentation typée de la config, défauts, résolution des chemins locaux. |
| `service/runner.py` | Cycle de vie portable (démarrage self-test, boucle, arrêt propre, reload). |
| `service/windows.py` | Service pywin32 (install/start/stop/run, mapping SvcStop→shutdown). |
| `service/linux.py` | Intégration systemd `Type=notify` (READY/WATCHDOG), gestion SIGTERM/SIGHUP. |
| `cli/commands.py` | `status`, `health`, `validate-config`, `trace`, `list-quarantine`, `replay`, `reconcile`, `reload`, `keys`. |
| `observability/metrics.py` | Collecte des compteurs/jauges/histogrammes, export textfile/JSON. |
| `observability/health.py` | Self-test (config, crypto), production de `health.json`. |

## 3. Principes de structuration

- **Dépendances dirigées vers le cœur** : `core` → `ports` ; `adapters`/`service`/`cli` →
  `core`+`ports`. Le cœur n'importe jamais un adaptateur ni un module OS.
- **Injection de dépendances** au câblage (composition root dans `service/runner.py`) :
  sélection des adaptateurs depuis la config (`backend: gnupg|pgpy`, etc.).
- **Testabilité** : chaque port a un adaptateur factice/in-memory dans `tests/fixtures`,
  permettant de tester le cœur sans IO réelle ni crypto réelle.
