# 13 — Operations guide

Runbook intended for support and operations. All operations rely on the
file system and the `filerouter` CLI (no database).

## 1. Administration CLI commands

| Command | Effect |
|----------|-------|
| `filerouter status` | Service state, backlog, quarantine, reconciliation freshness. |
| `filerouter health` | Self-test (config, crypto), return code for a probe. |
| `filerouter validate-config <path>` | Validates a YAML without starting. |
| `filerouter trace <technical_id>` | Reconstructs the history (correlated audit + logs). |
| `filerouter list-quarantine` | Lists the items in `runtime/error/`. |
| `filerouter replay <technical_id>` | Replays a quarantined item. |
| `filerouter reconcile` | Forces an immediate reconciliation. |
| `filerouter run` | Runs the service loop in the foreground. |
| `filerouter reload` | Reloads the config (revalidation + atomic swap). |
| `filerouter keys list` | Lists the keyring keys and their epochs. |

> **v1.0 scope**: implemented commands are `validate-config`, `health`, `trace`,
> `list-quarantine`, `reconcile` and `run`. The `status`, `replay`, `reload` and
> `keys list` commands are described here as the target and will be added in a later
> version (`list-quarantine` plus reading `runtime/error/<id>/error.json` covers
> diagnosis today; replay is currently done by re-dropping the source).

## 2. Common tasks

### 2.1 Track a file
1. Retrieve the `technical_id` (technical name or logs).
2. `filerouter trace <technical_id>` → full timeline (DETECTED → … → terminal).
3. In case of error: the `ERROR` event indicates `step`, `message`, `quarantine_path`.

### 2.2 Handle the quarantine
1. `filerouter list-quarantine`.
2. For each item: read `runtime/error/<id>/error.json`.
3. Fix the cause (key, config, permissions, disk space…).
4. `filerouter replay <id>`; verify completion via `trace`.

### 2.3 Configuration reload
1. `filerouter validate-config <new.yaml>`.
2. Replace the config file.
3. `filerouter reload` (the invalid config is rejected, the previous one stays active).

### 2.4 Key rotation
See [06 §4](06-encryption.md). Procedure: generate/publish the new sub-key, overlap
period, rule switch-over, removal of the old one after the flows have drained.

## 3. Start / stop

| Action | Windows | Linux |
|--------|---------|-------|
| Start | `sc start FileRouterService` | `systemctl start filerouter` |
| Stop (clean) | `sc stop FileRouterService` | `systemctl stop filerouter` |
| Status | `sc query FileRouterService` | `systemctl status filerouter` |

The stop is **cooperative**: the current item finishes, the locks are released, the logs
are flushed. An abrupt stop is recovered by reconciliation on restart ([16](16-disaster-recovery.md)).

## 4. Quick diagnosis

| Symptom | Check | Probable cause |
|----------|----------|----------------|
| Files not detected | inclusion/exclusion, permissions, stability | exclusion rule, file still being written |
| Rising backlog | workers, IO, stale locks | under-sizing, slow share |
| Rising quarantine | per-item `error.json` | key/signature, config, permissions, disk |
| No publication | disk space, exchange ACL | full disk, permissions |
| Integrity failures | security stream | transport corruption, tampering |
| Service does not start | `validate-config`, crypto self-test | invalid YAML, keyring/passphrase |

## 5. Operational best practices

- Continuously monitor `quarantine_current` (target: 0) and `oldest_pending_age`.
- **Never** manually delete an item from `processing/` without a `reconcile` (duplicate
  risk); prefer the CLI commands.
- Regularly back up `runtime/audit/`, `keys/` and the config.
- Test key rotation in pre-production before each deadline.
- Monitor the disk space of the `runtime`/`exchange` volume (mandatory alert).

## 6. Backup & restore

| Item | Backup | Restore |
|---------|-----------|--------------|
| Config YAML | VCS + backup | redeployment |
| Keys (`keys/`) | offline encrypted backup | re-import into `gnupg_home` |
| Audit (`runtime/audit/`) | regular backup | copy in place (append-only) |
| Archive | per policy | copy in place |

> `runtime/processing/`, `staging/`, `temp/`, `locks/` are **volatile**: they do not
> need to be backed up; reconciliation rebuilds/cleans them at startup.
