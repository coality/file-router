# 17 — Python project structure

## 1. Full tree

```text
file-router/
├── pyproject.toml                 # packaging, metadata, deps, tools
├── requirements.lock              # pinned dependencies
├── README.md
├── LICENSE
├── docs/                          # this specification
├── config/
│   └── config.example.yaml        # reference config
├── src/
│   └── filerouter/
│       ├── __init__.py
│       ├── __main__.py            # CLI entry point (python -m filerouter)
│       ├── version.py             # __version__, SCHEMA_VERSIONS
│       │
│       ├── core/                  # portable core (no direct OS/crypto dependency)
│       │   ├── __init__.py
│       │   ├── orchestrator.py    # scan loop, worker pool, cooperative shutdown
│       │   ├── outbound.py        # OutboundProcessor (10-step pipeline)
│       │   ├── inbound.py         # InboundProcessor (8-step pipeline)
│       │   ├── state_machine.py   # legal transitions + atomic operations
│       │   ├── naming.py          # naming engine + inverse mapping
│       │   ├── hashing.py         # streaming SHA-256, safe comparison
│       │   ├── metadata.py        # model, serialization, validation
│       │   ├── audit.py           # JSON-Lines write/read, reconstruction
│       │   ├── reconciliation.py  # startup reconciliation/recovery
│       │   ├── dedup.py           # FS duplicate index
│       │   ├── rules.py           # inclusion/exclusion, encryption rule matching
│       │   ├── pathing.py         # base_folder match, POSIX relative_path
│       │   ├── retention.py       # archive/audit/logs purge
│       │   ├── errors.py          # exception taxonomy
│       │   └── models.py          # dataclasses (FileItem, KeyInfo, VerificationResult…)
│       │
│       ├── ports/                 # interfaces (Protocol/ABC) — core contracts
│       │   ├── __init__.py
│       │   ├── file_store.py      # FileStore
│       │   ├── lock_manager.py    # LockManager
│       │   ├── crypto_provider.py # CryptoProvider
│       │   ├── clock.py           # Clock
│       │   ├── log_sink.py        # LogSink
│       │   └── id_generator.py    # IdGenerator
│       │
│       ├── adapters/              # concrete implementations of the ports
│       │   ├── __init__.py
│       │   ├── local_file_store.py     # os/pathlib, atomicity, cross-volume, stability
│       │   ├── file_lock_manager.py    # O_EXCL + heartbeat + reaper
│       │   ├── gnupg_provider.py       # GnuPG backend (python-gnupg)
│       │   ├── pgpy_provider.py        # PGPy backend (pure python)
│       │   ├── system_clock.py
│       │   ├── jsonl_log_sink.py       # 4 streams, rotation, compression, async
│       │   └── ulid_generator.py
│       │
│       ├── config/                # configuration
│       │   ├── __init__.py
│       │   ├── loader.py          # YAML loading (safe_load)
│       │   ├── schema.py          # jsonschema validation + semantic checks
│       │   └── model.py           # typed config dataclasses
│       │
│       ├── service/               # service wrappers (only OS-specific code)
│       │   ├── __init__.py
│       │   ├── runner.py          # portable orchestrator start/stop
│       │   ├── windows.py         # pywin32 service (install/start/stop/run)
│       │   └── linux.py           # systemd daemon (Type=notify, watchdog)
│       │
│       ├── cli/                   # administration commands
│       │   ├── __init__.py
│       │   └── commands.py        # status, health, trace, replay, reconcile, reload, keys…
│       │
│       └── observability/
│           ├── __init__.py
│           ├── metrics.py         # collection + export (textfile/json)
│           └── health.py          # self-test, health.json
│
├── schemas/                       # JSON Schemas (referenced by docs/schemas)
│   ├── metadata.schema.json
│   ├── audit.schema.json
│   └── config.schema.json
│
└── tests/                         # see 18-testing-strategy.md
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

## 2. Module description

### `core/` (portable)

| Module | Responsibility |
|--------|----------------|
| `orchestrator.py` | Scan loop (`scan_interval`), outbound/inbound enumeration with rules, dispatch to the bounded worker pool, cooperative shutdown, triggering of reconciliation. |
| `outbound.py` | 10-step outbound pipeline; each step idempotent, emits an audit, advances the state machine. |
| `inbound.py` | 8-step inbound pipeline; strict validation order (payload-hash → sig+decryption → clear-hash → move). |
| `state_machine.py` | Defines the legal transitions and exposes the atomic operations (move/publish via FileStore). Single authority over state. |
| `naming.py` | Renders the technical name from the pattern, applies `max_length`/charset, generates `technical_id`, restores the original name from the metadata. |
| `hashing.py` | Streaming SHA-256 (constant memory), constant-time comparison. |
| `metadata.py` | Builds/serializes/validates the metadata; guarantees the invariants (encrypted⇒encryption, POSIX relative_path). |
| `audit.py` | Writes the JSON-Lines events (temp+rename for the file, append for the lines), reconstructs the history, provides the last state. |
| `reconciliation.py` | Classifies and handles the orphans (`temp/`, `processing/`, `staging/`, `locks/`, exchange), relaunch/finalize/quarantine. |
| `dedup.py` | FS duplicate index (`O_EXCL` markers per hash); skip/overwrite/error policies. |
| `rules.py` | Compiles and evaluates inclusion/exclusion (glob) and encryption rules (alias + path_pattern). |
| `pathing.py` | Identifies the base_folder by longest prefix; computes POSIX-normalized `relative_path`; rebuilds `base_path / relative_path`. |
| `retention.py` | Idempotent/interruptible purge sweep for archive/audit/logs/dedup. |
| `errors.py` | Typed exception hierarchy (Transient, Integrity, Crypto, Config, Data). |
| `models.py` | Domain dataclasses (FileItem, Metadata, AuditEvent, KeyInfo, VerificationResult). |

### `ports/` & `adapters/`

| Port | Adapter(s) | Notes |
|------|---------------|-------|
| `FileStore` | `local_file_store.py` | `os.replace`, cross-volume copy+fsync, enumeration, stable-size check, exclusive-open probe (Windows). |
| `LockManager` | `file_lock_manager.py` | `O_EXCL` lock, heartbeat, stale detection/reclamation. |
| `CryptoProvider` | `gnupg_provider.py`, `pgpy_provider.py` | encrypt/decrypt/sign/verify/list_keys; self-test at boot. |
| `Clock` | `system_clock.py` | monotonic time + UTC; injectable for tests (frozen clock). |
| `LogSink` | `jsonl_log_sink.py` | 4 JSON-Lines streams, rotation/compression, non-blocking async writing. |
| `IdGenerator` | `ulid_generator.py` | `technical_id` ULID (orderable) or UUIDv4. |

### `config/`, `service/`, `cli/`, `observability/`

| Module | Responsibility |
|--------|----------------|
| `config/loader.py` | Safe YAML loading (`yaml.safe_load`). |
| `config/schema.py` | `jsonschema` validation + semantic checks (unique aliases, same runtime/exchange volume, pattern contains `{technical_id}`, keys present). |
| `config/model.py` | Typed representation of the config, defaults, resolution of local paths. |
| `service/runner.py` | Portable lifecycle (startup self-test, loop, clean stop, reload). |
| `service/windows.py` | pywin32 service (install/start/stop/run, SvcStop→shutdown mapping). |
| `service/linux.py` | systemd `Type=notify` integration (READY/WATCHDOG), SIGTERM/SIGHUP handling. |
| `cli/commands.py` | `status`, `health`, `validate-config`, `trace`, `list-quarantine`, `replay`, `reconcile`, `reload`, `keys`. |
| `observability/metrics.py` | Collection of counters/gauges/histograms, textfile/JSON export. |
| `observability/health.py` | Self-test (config, crypto), production of `health.json`. |

## 3. Structuring principles

- **Dependencies directed toward the core**: `core` → `ports`; `adapters`/`service`/`cli` →
  `core`+`ports`. The core never imports an adapter nor an OS module.
- **Dependency injection** at wiring time (composition root in `service/runner.py`):
  adapter selection from the config (`backend: gnupg|pgpy`, etc.).
- **Testability**: each port has a fake/in-memory adapter in `tests/fixtures`,
  allowing the core to be tested without real IO or real crypto.
