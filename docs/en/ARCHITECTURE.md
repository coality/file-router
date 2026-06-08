# FileRouter — Architecture document

> Consolidated technical overview. For per-topic detail, see the numbered
> chapters `00`–`18` in this folder.

## 1. Purpose and principles

FileRouter is a **local, network-less, database-less enterprise file router**. It
detects files in business directories, computes their digests, optionally
compresses/encrypts/signs them, renames them and drops them into flat exchange
directories. On receipt it validates, decrypts, rebuilds the business tree and
delivers.

Guiding principles:

- **Zero database**: the **filesystem is the single source of truth**. No external
  dependency to install/back up/secure.
- **No network transport**: cross-site transfer is external (MFT, replication,
  shared storage) — out of scope.
- **Atomicity + idempotency**: atomic operations (intra-volume rename), crash
  recovery with no loss and no double publish.
- **Reconstructible per-file audit** + a human-readable transfer journal.
- **Cross-platform**: portable core, native Windows service (pywin32) and systemd.

## 2. Hexagonal architecture

| Layer | Content |
|-------|---------|
| `core/` | Pure domain (pipelines, rules, hashing, paths, state). No concrete I/O. |
| `ports/` | Interfaces: `FileStore`, `CryptoProvider`, `Clock`, `IdGenerator`, `LockManager`, `LogSink`. |
| `adapters/` | Implementations: local FS, GnuPG/PGPy/noop, ULID, file locks, JSONL. |
| `config/` | Typed model + YAML loading (`safe_load`) + JSON-Schema validation. |
| `cli/`, `service/` | Entry points: CLI, Windows / systemd service, composition (`runner`). |

The **`Context`** (frozen dataclass) bundles every port wired once at startup
(`service/runner.py:build_context`), keeping each processor method tiny.

## 3. Outbound flow (business → `exchange_out`)

`core/outbound.py`, transactional pipeline (any error → quarantine, source never
lost):

1. detect (stability required, see §6);
2. lock the source;
3. move into `processing/<id>/clear`;
4. SHA-256 of the clear file;
5. deduplication (configurable policy);
6. **compress (gzip) THEN encrypt (OpenPGP)** per rules;
7. payload hash;
8. technical name (`naming`);
9. **publish**: payload → (detached metadata signature) → metadata (guaranteed order);
10. archive/delete the source; record the transfer.

## 4. Inbound flow (`exchange_in` → business)

`core/inbound.py`, strict validation order:

1. **DB-less readiness**: pair presence (payload + metadata, + `.sig` if the sender
   signed), stability, age (mtime) — survives restarts;
2. move the pair into `processing/<id>/`;
3. **verify the payload hash BEFORE any crypto** (anti-corruption);
4. **verify the detached metadata signature** (authenticates routing fields);
5. decrypt + **verify the content signature** and the **authorized signer**;
6. decompress;
7. **verify the clear-text hash** (end-to-end integrity);
8. rebuild the business path (alias → local path + `relative_path` +
   `original_filename`) and deliver atomically; record.

## 5. State model, quarantine, recovery

- A file's state is **implicit**: its location + its audit trail.
- Any error → `runtime/error/<id>/` with `error.json`; never deliver "on doubt".
- `reconcile` (at startup and periodically) cleans orphaned `processing/`, re-arms
  recoverable items — idempotent.
- Deduplication: per-hash `O_EXCL` markers under `runtime/dedup/`.

## 6. Stability (files still being copied)

`LocalFileStore.is_stable` combines **quiescence** (size + mtime unchanged across N
samples spaced by `stability_interval_seconds`) and an **exclusive open** (on
Windows it fails while a writer holds the file). Producer recommendation: write to
`.tmp`/`.part` then rename (excluded by default). See
[13-operations-guide](13-operations-guide.md).

## 7. Cryptography

Three backends behind `CryptoProvider`:

- **`noop`**: no encryption (passthrough).
- **`pgpy`**: pure Python, **file-based keys** (`private_key_file`,
  `public_key_file`, `passphrase_file`) — no keyring to manage.
- **`gnupg`**: via `gpg` (keyring `gnupg_home` + key IDs).

Content is **encrypted AND signed**; the **metadata is signed separately**
(detached signature) to authenticate routing fields. The private-key passphrase
comes from the environment or an **ACL-restricted file**, never from the YAML.

## 8. Formats, audit, journal

- **Technical name**: configurable pattern
  (`{flow}_{direction}_{timestamp}_{technical_id}.{ext}`), portable charset,
  Windows reserved names handled.
- **Metadata** (`*.meta.json`): everything needed to rebuild and audit + clear/payload hashes.
- **Audit**: JSON-Lines events per `technical_id` (metadata ↔ audit ↔ logs correlation).
- **Transfer journal** (`logs/transfers.log`): one readable line per transfer (date,
  direction, names, clear/encrypted/signed/compressed flags, SHA-256, paths) — for support.

## 9. Concurrency and portability

- Coordination **via filesystem locks only** → works across threads, processes, or
  multiple hosts sharing storage (UNC supported; keep `runtime`/`exchange` on the
  same share for atomic renames).
- **Native Windows service** (pywin32, multi-instance, under a service account) and
  Linux **systemd**. The core is identical on both OSes (case-insensitive,
  POSIX-normalized path matching).

## 10. Distribution

- Python wheel + venv, OR a **fully self-contained portable Windows bundle**
  (embedded Python + dependencies + GnuPG) — see [12-deployment](12-deployment.md)
  and the README. In-place upgrade without overwriting the configuration.
