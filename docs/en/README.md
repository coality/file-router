# FileRouter — Technical Specification

FileRouter is a **local, network-free file router** intended for enterprise
environments. It detects files in business directories, computes metadata and
SHA-256 hashes, optionally encrypts/signs the files via OpenPGP, renames them with a
configurable technical name, then moves them through **flat** `exchange_out` /
`exchange_in` exchange directories. On the receiving side, it validates, decrypts,
restores the original name and rebuilds the business directory tree of unlimited depth.

> **No database.** All state lives on the file system: metadata files, audit files,
> lock files and technical directories.

## Reading order

| # | Document | Topic |
|---|----------|-------|
| 00 | [Overview](00-overview.md) | Context, objectives, scope, glossary, design principles |
| 01 | [Architecture](01-architecture.md) | Hexagonal design, component diagrams |
| 02 | [Flows](02-flows.md) | Outbound/inbound flow and sequence diagrams |
| 03 | [State management](03-state-management.md) | `runtime/`, state machine, atomicity, locking, recovery |
| 04 | [Data formats](04-data-formats.md) | Metadata JSON, audit JSON, naming convention |
| 05 | [Configuration](05-configuration.md) | Full YAML schema |
| 06 | [Encryption](06-encryption.md) | OpenPGP architecture, key management/rotation, signing |
| 07 | [Hashing](07-hashing.md) | Clear/payload SHA-256 hashes and validation order |
| 08 | [Observability](08-observability.md) | Logs, metrics, monitoring policy |
| 09 | [Error handling](09-error-handling.md) | Error taxonomy, retries, duplicates |
| 10 | [Security policy](10-security-policy.md) | Threat model, hardening |
| 11 | [Archival & retention](11-archival-retention.md) | Archival policy, retention |
| 12 | [Deployment](12-deployment.md) | Multi-platform, Windows service, Linux systemd |
| 13 | [Operations guide](13-operations-guide.md) | Runbook for support/operations |
| 14 | [Risk analysis](14-risk-analysis.md) | Risk register |
| 15 | [Versioning & upgrade](15-versioning-upgrade.md) | Migration and upgrade strategy |
| 16 | [Disaster recovery](16-disaster-recovery.md) | Recovery strategy |
| 17 | [Project structure](17-project-structure.md) | Python tree + per-module description |
| 18 | [Testing strategy](18-testing-strategy.md) | All test categories |

### Machine-checkable artifacts

- Schemas: [`schemas/metadata.schema.json`](../schemas/metadata.schema.json),
  [`schemas/audit.schema.json`](../schemas/audit.schema.json),
  [`schemas/config.schema.json`](../schemas/config.schema.json)
- Examples: [`examples/config.example.yaml`](../examples/config.example.yaml),
  [`examples/PAYMENT_OUT_20260608T120000_ABC123.meta.json`](../examples/PAYMENT_OUT_20260608T120000_ABC123.meta.json),
  [`examples/ABC123.audit.json`](../examples/ABC123.audit.json)

## Target platform

- Windows Server 2019+ (primary target, native service via pywin32) **and** Linux (systemd).
- Python 3.12+.
- The portable core contains no OS-specific code; platform specifics are isolated
  in adapters.

## Status

Specification v1.0 — design only, no implementation in this deliverable.
