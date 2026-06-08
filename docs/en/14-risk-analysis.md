# 14 — Risk analysis

Risk register with probability (P), impact (I) and criticality (P×I) on a
1–5 scale, and mitigation measures. See also [10](10-security-policy.md), [09](09-error-handling.md),
[16](16-disaster-recovery.md).

## 1. Risk register

| ID | Risk | P | I | Crit. | Mitigation |
|----|--------|---|---|-------|------------|
| R01 | File loss (crash during a move) | 2 | 5 | 10 | Atomic rename + write-then-rename + reconciliation; never a deletion before confirmed publication |
| R02 | Partial publication of a file (reading a file being written) | 2 | 4 | 8 | temp-then-rename; stable-size check before detection |
| R03 | Payload alteration in transit | 2 | 5 | 10 | `payload_file_hash` verified before decryption; quarantine |
| R04 | Business content alteration | 1 | 5 | 5 | `clear_file_hash` after decryption; signature |
| R05 | Fake sender / impersonation | 2 | 5 | 10 | Mandatory signature + authorized signers |
| R06 | Leak of sensitive data | 2 | 5 | 10 | OpenPGP encryption, FS permissions, secrets out of config |
| R07 | Private key compromise | 1 | 5 | 5 | Offline master key, sub-keys, rotation/revocation, vault |
| R08 | Duplicates (re-emission, replay) | 3 | 3 | 9 | FS dedup index, idempotence, skip/overwrite policies |
| R09 | Stale lock blocking a file | 2 | 3 | 6 | TTL + heartbeat + reaper; liveness check |
| R10 | Disk saturation (runtime/exchange) | 3 | 4 | 12 | Disk alert, retention purge, bounded backlog |
| R11 | Undrained backlog (under-sizing) | 2 | 3 | 6 | `oldest_pending` metrics, worker scaling |
| R12 | Erroneous config deployed | 2 | 4 | 8 | Schema validation, fail-fast, reload rejects the invalid |
| R13 | Business tree corruption (name collision inbound) | 2 | 4 | 8 | Restore from metadata, duplicate policy, atomic mkdir |
| R14 | Crypto backend (gpg) unavailability | 1 | 4 | 4 | Self-test at boot, fail-fast, prerequisites doc |
| R15 | Repeated crash / runtime corruption | 1 | 4 | 4 | Recoverable finite states, quarantine, monitoring |
| R16 | Non-atomic cross-volume | 2 | 4 | 8 | Copy+fsync+rename; purge of `*.partial` |
| R17 | Unsynchronized clock (inconsistent timestamps) | 2 | 2 | 4 | NTP required; `technical_id` (ULID) remains unique and orderable |
| R18 | Vulnerable dependency (software supply chain) | 2 | 4 | 8 | Pinned versions, SBOM, CI scan ([15](15-versioning-upgrade.md)) |
| R19 | Unhandled quarantine volume | 2 | 3 | 6 | `quarantine_current` alert, runbook, never auto-deleted |
| R20 | Loss of the keyring | 1 | 5 | 5 | Offline encrypted backup, restore procedure |

## 2. Major risks (criticality ≥ 9) — focus

- **R10 (disk, 12)**: operational risk #1. Mitigation = proactive monitoring +
  automatic purge + documented sizing ([11](11-archival-retention.md)).
- **R01/R03/R05/R06 (10)**: covered by the design invariants (atomicity,
  double-hash, signature, encryption). None of these risks must be able to cause a
  silent loss/leak — always quarantine + alert.
- **R08 (9)**: duplicates handled without a database via FS index and idempotence
  ([09 §5](09-error-handling.md)).

## 3. Accepted residual risks

- External transport out of scope: FileRouter detects corruption (hash) but does not guarantee
  delivery — responsibility of the transport mechanism.
- Availability dependent on the underlying OS/storage (cluster/SAN out of scope).

## 4. Follow-up

Risks are reviewed at each major upgrade and after every incident
(post-mortem feeding the table). The metrics in [08](08-observability.md) provide the
leading indicators (backlog, quarantine, stale locks, integrity failures).
