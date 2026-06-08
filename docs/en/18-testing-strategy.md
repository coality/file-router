# 18 — Testing strategy

Goal: maximum coverage over all the requested categories. Tools:
`pytest`, `pytest-cov`, `hypothesis` (property-based), `freezegun`/injected clock,
`pyfakefs` (fake FS) and a real temporary FS for the integration tests.

## 1. Pyramid & organization

```text
tests/
├── unit/            # core isolated via fake adapters
├── integration/     # real temporary FS + real gpg (test keys)
├── load/            # throughput/volume/concurrency
├── security/        # crypto, signatures, integrity, hardening
├── recovery/        # crash/recovery, reconciliation, orphans
├── regression/      # cross-version metadata/audit/config compatibility
├── fs_robustness/   # extreme filesystem behaviors
├── fixtures/        # in-memory adapters, key sets, item factories
└── conftest.py
```

Coverage target: **≥ 90%** on `core/`, **≥ 80%** overall. All tests run in
CI on Linux **and** Windows (matrix) to validate multi-platform parity.

## 2. Unit tests

Core tested without real IO or crypto (fake adapters):

- `naming`: pattern rendering, `max_length` truncation/rejection, portable charset, reserved
  Windows names, `technical_id` uniqueness, original name restoration.
- `pathing`: base_folder identification by longest prefix, POSIX `relative_path`,
  unlimited depth, rejection of absolute/`..` paths.
- `hashing`: known SHA-256 vectors, large-file streaming (constant memory),
  constant-time comparison.
- `metadata`/`audit`: invariants (encrypted⇒encryption, payload==clear if not encrypted),
  serialization, history reconstruction, `seq` numbers.
- `rules`: inclusion/exclusion (exclusion prioritized), encryption rule matching.
- `state_machine`: only legal transitions are allowed.
- `dedup`: first-come-wins, skip/overwrite/error policies.
- **Property-based** (`hypothesis`): for any path/at any depth,
  `base_path / relative_path` rebuilds the business path; original-name round-trip.

## 3. Integration tests

On a real temporary FS, with a real gpg test keyring:

- Full **outbound** pipeline: detection → … → `exchange_out` + metadata + audit + archive.
- Full **inbound** pipeline: `exchange_in` → validation → decryption → business.
- **Round-trip** sender↔receiver: a file goes through both pipelines and comes back
  bit-for-bit identical, business tree rebuilt identically.
- Inter-server mapping: same aliases, different physical paths.
- Crypto backends: same tests on `gnupg` **and** `pgpy`.
- Cross-volume (if applicable in CI): copy+fsync+rename.

## 4. Load tests

- **Throughput**: N thousands of files (varied sizes: KB → several GB); measure end-to-end
  latency and throughput.
- **Concurrency**: saturated worker pool; verify one-writer-per-file (no
  double processing) under lock contention.
- **Large files**: bounded memory (streaming hash/crypto) — no memory spike with the
  size.
- **Backlog**: burst injection; verify the absence of loss and the draining.
- **Endurance** (soak): prolonged run; absence of leaks (descriptors, memory,
  residual locks).

## 5. Security tests

- **Integrity**: alter the payload → `payload_file_hash` failure → quarantine, never
  an integration. Likewise post-decryption alteration → `clear_file_hash`.
- **Signature**: missing / invalid / unauthorized-signer signature → `ERROR` +
  quarantine.
- **Confidentiality**: the payload in the exchange is indeed encrypted; no clear leaks.
- **Validation order**: prove that decryption does not happen before the validation of the
  payload-hash.
- **Input hardening**: corrupted metadata, `..`/absolute paths, reserved names, malicious
  YAML (`safe_load`) → clean rejection.
- **Secrets**: no passphrase in clear in the config; FS permissions of the keyring.
- Key **rotation/revocation**: epoch overlap, revocation honored.

## 6. Disaster recovery tests

Crash simulation by injecting a failure **at each step** of the pipeline (worker kill /
targeted exception), then reconciliation and verification of the **no loss nor double
publication** invariant:

- Crash after each transition (before/after each atomic rename).
- Outage during cross-volume copy → only `*.partial`, purged.
- Stale lock → taken over by the reaper after TTL.
- Incomplete exchange pair → quarantine after grace.
- Resumption from the last audit event (reuse of valid outputs).
- **Replay** idempotence: a replayed item does not produce a duplicate.
- RPO≈0 verified: any validated file is either delivered or replayable, never lost.

## 7. Regression tests

- **Schema compatibility**: an earlier `schema_version` metadata is read (forward
  tolerance); unknown fields ignored.
- **Receivers-before-senders order**: a version-N receiver reads an N-1 format.
- **Snapshots** of the outputs (technical name, metadata, audit sequence) to freeze the
  behavior; any deviation is flagged.
- Set of **golden files** for the formats.

## 8. Filesystem robustness tests

- **Partial writes**: interruption mid-write → never a visible partial file
  (temp+rename).
- **File being written by a third party**: not detected as long as the size is not
  stable; exclusive-open probe (Windows).
- **Permissions**: read/write/delete refusal → handled error + quarantine, no
  crash.
- **Disk full** (simulated `ENOSPC`): transient error → retry → quarantine + alert.
- **Extreme names**: very long, Unicode, special characters, case (case-insensitive NTFS vs
  case-sensitive ext4).
- **Deep paths**: very deep tree (unlimited depth) inbound/outbound.
- **Atomic rename**: prove that after an interruption, only the old **or** the new name
  exists.
- **Cross-volume**: cross-device `os.replace` fails cleanly → copy+rename path.
- **Clock**: tests with an injected clock (timestamp determinism).

## 9. Continuous integration

- **Linux + Windows** matrix, Python 3.12+.
- Steps: lint (`ruff`), typing (`mypy`), unit+integration tests, coverage, dependency
  vulnerability scan, validation of the examples against the schemas
  ([README](README.md)).
- The load/endurance tests run in a scheduled pipeline (nightly), not on every commit.
