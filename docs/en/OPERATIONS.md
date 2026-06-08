# FileRouter — Operations document

> Consolidated operations/support guide. Complements
> [13-operations-guide](13-operations-guide.md) and [12-deployment](12-deployment.md).

## 1. Installation

### Portable Windows bundle (recommended, nothing to install)
Unzip, then (once) create your config from the template:
```powershell
copy config\config.example.yaml config\config.yaml
filerouter-doctor.bat --config config\config.yaml --fix --yes
filerouter.bat        --config config\config.yaml validate-config
filerouter.bat        --config config\config.yaml run
```
Python AND GnuPG are embedded. Compatible with Windows 10/11 and Server 2016→2025 (x64).

### From source (venv)
`pip install ".[windows]"` (Windows) or `pip install "."` (Linux); add `gnupg`/`pgpy`
depending on the encryption backend.

## 2. Configuration

- `base_folders` (alias → path), `exchange`, `runtime`, `naming`, `hashing`.
- `inclusion`/`exclusion`: **case-insensitive** globs, identical on Linux/Windows.
  Filter by extension: `inclusion: { patterns: ["*.csv", "*.xml"] }`.
  Ignore a directory: `exclusion: { patterns: ["archive/**", "*/archive/*"] }`.
- **Encryption**:
  - `backend: pgpy` → `private_key_file`, `public_key_file`, `passphrase_file` (paths; ACL to the service account);
  - `backend: gnupg` → `gnupg_home`, `signing_key_id`, `recipient_key_ids`, passphrase via env/file.
- **Always validate**: `filerouter ... validate-config`. **Diagnose**: `filerouter-doctor`.

## 3. CLI commands

| Command | Use |
|---------|-----|
| `validate-config` | Validate the config without starting |
| `health` | Self-test (config, crypto) |
| `preview [--watched-only]` | Read-only: watched/skipped files (+ reason) and inbound pairs |
| `history [--limit N]` | Human-readable transfer journal (support) |
| `trace <technical_id>` | Correlated audit history of a file |
| `list-quarantine` | Items under `runtime/error/` |
| `reconcile` | Immediate reconciliation (recovery) |
| `run` | Service loop in the foreground |
| `doctor [--fix] [--yes]` | Config/environment diagnostics |

## 4. Running as a service

### Windows (under a service account — recommended for UNC)
```powershell
filerouter-service.bat install --config "%CD%\config\config.yaml" ^
    --username "DOMAIN\svc_filerouter" --password "***" --startup auto
filerouter-service.bat start
```
Multi-instance: `... install --instance siteA --config <…>` creates `FileRouter_siteA`.
The account needs "Log on as a service" and access to the business/exchange/runtime
directories (and the keyring/secret).

### Linux (systemd)
See the unit template in [12-deployment](12-deployment.md#4-linux--systemd).

## 5. Monitoring

- **Health**: `health` (return code for a probe).
- **Backlog/quarantine**: watch `runtime/error/` (target: 0); `list-quarantine` then
  read `runtime/error/<id>/error.json`.
- **Support history**: `history` or open `logs/transfers.log` (date, direction,
  names, encrypted/signed/compressed flags, SHA-256, paths).
- **Structured logs**: JSON-Lines streams under `logs/` (projectable to a SIEM).

## 6. Large files still being copied

FileRouter processes a file only once it is **stable** (size+mtime unchanged across
`stability_checks` samples spaced by `stability_interval_seconds`, + exclusive open
on Windows). For very large files / slow transports, raise both values. **Producer
best practice**: write to `.tmp`/`.part` then rename (excluded by default) → the
file only appears once complete.

## 7. In-place upgrade (no breakage, no config overwrite)

1. Stop the service (`filerouter-service.bat stop`); if the embedded gnupg was used,
   stop the agent (`gpgconf --kill all`).
2. Unzip the new archive into the **same `filerouter\` folder**: the program is
   replaced; **`config.yaml` is never overwritten** (the archive ships only
   `config.example.yaml`).
3. Restart the service.
Keep `runtime`/`exchange`/keyring/secret **outside** the bundle folder.

## 8. Backup & disaster recovery

- State lives on the FS: back up `runtime/` (audit, dedup, quarantine), the config
  and the keyring/secret. No database to back up.
- On restart, `reconcile` replays recovery (idempotent operations).

## 9. Quick troubleshooting

| Symptom | Lead |
|---------|------|
| Service won't start | `validate-config`; account rights; config access (`FILEROUTER_CONFIG_<INSTANCE>`) |
| Nothing is routed | `preview` (inclusion/exclusion rules); stability; instance role |
| File quarantined | `runtime/error/<id>/error.json`; hash/signature/key |
| Encryption fails | `health`; key presence; passphrase (env/file); backend |
| UNC access denied (service) | use a **domain service account** (not LocalSystem) |
