# 10 — Security policy

## 1. Security objectives

| Property | Mechanism |
|-----------|-----------|
| **Confidentiality** | OpenPGP encryption of sensitive files ([06](06-encryption.md)) |
| **Integrity** | Double SHA-256 hash (payload + clear) ([07](07-hashing.md)) |
| **Authenticity** | OpenPGP signature + signer whitelist |
| **Traceability** | Append-only per-file audit + security logs |
| **Non-repudiation** | Verified and logged signature (signer_key_id) |
| **Availability** | Disaster recovery, fail safe, monitoring |

## 2. Threat model (STRIDE summary)

| Threat | Scenario | Countermeasure |
|--------|----------|---------------|
| **Spoofing** | Fake sender drops a payload | Mandatory signature + authorized signers (`require_signature_inbound`) |
| **Tampering** | Alteration of the payload in transit | `payload_file_hash` verified **before** decryption |
| **Tampering** | Alteration of the business content | `clear_file_hash` verified after decryption |
| **Repudiation** | Denial of emission | Signature + audit + security logs |
| **Information disclosure** | Reading sensitive files at rest/in transit | OpenPGP encryption, FS permissions, encrypted payload in the exchange |
| **DoS** | Saturation by files/quarantine | Bounded backlog, monitoring, isolated quarantine |
| **Elevation of privilege** | Compromise of the service account | Least privilege, keyring isolation, passphrase out of config |

## 3. Secrets management

- **No secret in clear in the YAML.** Private-key passphrases supplied via a protected
  environment variable, a restricted-permission file outside VCS, or a vault
  (DPAPI/Credential Manager on Windows, systemd secret/vault on Linux).
- Keyrings (`gnupg_home`) with access restricted to the service account only.
- The OpenPGP master key stays **offline**; only the service sub-keys are deployed
  ([06 §3](06-encryption.md)).
- Rotation and revocation: see [06 §4](06-encryption.md).

## 4. Filesystem access control

| Path | Access |
|--------|-------|
| `runtime/`, `logs/`, `keys/` | Service account only (RW), administrators (R) |
| `exchange_in` / `exchange_out` | Service account (RW) + external transport agent (RW) |
| `base_folders` | Service account (RW) + business applications |
| Config YAML | Service account (R), administrators (RW) |

- Execution under a **dedicated, non-administrator service account**, with least privilege.
- On Windows: explicit ACLs; service running *Log on as* a managed account (gMSA recommended).
- On Linux: dedicated system user, restrictive umask, `ProtectSystem`/`PrivateTmp`
  via systemd (see [12](12-deployment.md)).

## 5. Security of quarantined data

Quarantined payloads can be **encrypted** (nominal case): they remain
confidential. Any clear files (post-decryption failure) inherit the
restricted permissions of `runtime/error/` and are subject to the same access policy.

## 6. Security logging

The **security** stream ([08](08-observability.md)) records: encryptions/decryptions,
signature verification results (signer_key_id, validity), integrity failures, key
access, rotations. These logs have long retention and are write-protected (append-only,
optional signed rotation).

## 7. Application hardening

- Strict input validation (metadata, names, paths); rejection of absolute paths, of
  `..` traversals, of reserved names.
- No dangerous deserialization (JSON/YAML in safe mode — `yaml.safe_load`).
- No content execution; no system call derived from untrusted data.
- Pinned and audited dependencies (SBOM, CI vulnerability scan) ([15](15-versioning-upgrade.md)).
- Compliance: the double hash + signature + append-only audit meet the
  integrity and audit-trail requirements (e.g. SOX/ISO 27001) without a database.

## 8. Incident response

- Key compromise → revocation + emergency rotation + re-encryption of the affected flows.
- Tampering detection (integrity/signature) → automatic quarantine + SOC alert +
  preservation of the item for forensic analysis (the audit provides the full timeline).
