# FileRouter — Security document

> **Self-contained, generalist** document, intended for a security / compliance
> team **with no prior knowledge** of the project. It introduces the application
> and the data it handles, then all of the security measures.

---

## 0. In one sentence

FileRouter is a **piece of software that transfers files between two sites
securely**, encrypting and signing them, **with no database and doing no
networking itself**: network transport is handled by an existing third-party tool;
FileRouter handles preparation, protection, integrity checking and rebuilding of
the files.

## 1. What the application does

**Problem solved.** Exchange business files (e.g. accounting `.csv`, payment `.xml`)
between two sites/servers, reliably and confidentially, without deploying new
infrastructure (no database, no extra network service to expose).

**Overview.**

```
 SITE A (sender)                   third-party transport         SITE B (receiver)
 business dir   --FileRouter-->  exchange_out  ==MFT/share==>  exchange_in  --FileRouter-->  business dir
 (e.g. \\srv\acct) detects         (flat drop)  (out of scope)  (flat drop)   validate&deliver (e.g. \\srv\acct)
                  hash, compress,                               verify hash,
                  encrypt, sign                                 decrypt, verify
                                                                signature, rebuild
```

1. On **send**: watch **business directories**, detect new files, SHA-256 digest,
   **compress** then **encrypt + sign** (OpenPGP), rename, drop into `exchange_out`.
2. **Third-party transport** (MFT, replication, share) — **out of scope** — moves
   the files to the remote site.
3. On **receive**: read `exchange_in`, **verify digest + signature**, **decrypt**,
   decompress, **rebuild the original tree** and deliver.

**What FileRouter does NOT do**: no network connection, no database, no exposed
port. All of its state lives in local files.

## 2. Glossary

| Term | Meaning |
|------|---------|
| **Business directory** (`base_folder`) | Watched folder holding the files to transfer. |
| **`exchange_out` / `exchange_in`** | "Outbox / inbox" folders at the boundary with the third-party transport. |
| **Payload** | The file as it travels (encrypted/compressed). |
| **Metadata** (`*.meta.json`) | Technical sheet beside the payload (names, paths, digests) used to rebuild and audit. |
| **`technical_id`** | Unique id (ULID) per transfer; correlation key across logs. |
| **OpenPGP** | Encryption/signature standard (RFC 4880); `gnupg` or `pgpy` engines. |
| **Quarantine** | Folder where failed files are isolated, never delivered "on doubt". |

## 3. Data handled

| Data | Sensitivity | Protection |
|------|-------------|------------|
| Business files | Potentially sensitive | Encrypted + signed in transit; digests verified |
| Private key | Secret | Access-restricted file/keyring (service account) |
| Passphrase | Secret | Env var or ACL-restricted file; never in the config |
| Metadata | Internal | Signed (routing integrity) |
| Logs / audit | Internal | No secrets; consumable by a SIEM |

## 4. Threat model

- **Trust boundary**: `exchange_out`/`exchange_in` are the boundary with the
  third-party transport; depending on the trust placed in it, the content of
  `exchange_in` may be influenced by an attacker with access to the channel/share.
- **Assets**: confidentiality and integrity of files; private key and passphrase;
  **routing integrity** (delivery destination).
- **Considered attacks**: corruption in transit; metadata tampering (redirection);
  unsigned files or files signed by a non-authorized party; path traversal via
  metadata fields.

## 5. Security measures

### 5.1 Secrets
- **No secret in the configuration** (YAML): only **paths** and **key identifiers**.
- **Passphrase**: env var `FILEROUTER_GPG_PASSPHRASE` (takes precedence) or a
  `passphrase_file` with an ACL restricted to the **service account**.
- **Private key**: `private_key_file` (restricted ACL) or GnuPG keyring.
- **No secret written to logs** (only key identifiers, digests, paths).

```powershell
icacls C:\ProgramData\FileRouter\secrets\gpg.pass /inheritance:r
icacls C:\ProgramData\FileRouter\secrets\gpg.pass /grant "DOMAIN\svc_filerouter:R" "SYSTEM:R"
```

### 5.2 Encryption and signing
- Content is **encrypted AND signed** (OpenPGP). A single key pair can provide both
  encryption and signing (signing primary key + encryption subkey), or separate keys
  per policy.

### 5.3 Integrity and authenticity (receive)
Strict verification order:
1. payload digest **before any decryption** (anti-corruption);
2. decryption;
3. **content signature** + check that the **signer is authorized** (whitelist);
4. clear-text digest (end-to-end integrity);
5. **metadata signature** (detached): authenticates the routing fields (path, name,
   alias) to prevent redirection of a signed file.

### 5.4 Path traversal
Routing fields from the metadata (`technical_id`, `relative_path`) are **strictly
validated** (no `/`, `\`, or `..`) before any use as a filesystem path.

### 5.5 Permissions
`filerouter-doctor` **reports** permission problems but **never modifies**
permissions (it may only create a missing directory — an explicit, safe action).

### 5.6 Running under a service account (least privilege)
The application runs under a **dedicated service account** (neither administrator
nor system), with access limited to only the necessary directories. Recommended: a
group Managed Service Account (gMSA) with no password where AD allows.

### 5.7 Error isolation
Any anomaly (digest, signature, decryption, IO) **isolates the file in quarantine**
with an error report; **never delivered "on doubt"**.

### 5.8 Observability
Per-file audit log + a human-readable transfer journal (date, direction, names,
applied protections, digest), with no secrets, consumable by a SIEM.

## 6. Controls summary

| Control | Mechanism |
|---------|-----------|
| Confidentiality | OpenPGP encryption of content |
| Integrity | SHA-256 digests (payload + clear) verified |
| Sender authenticity | Content signature + signer whitelist |
| Routing integrity | Detached metadata signature |
| Secret protection | Out of configuration; ACL; never logged |
| Anti-traversal | Strict validation of path fields |
| Least privilege | Dedicated service account |
| Containment | Quarantine of errors |
| Traceability | Per-file audit + transfer journal |

## 7. Hardening recommendations (deployment)

- **Transport**: keep `exchange_in` a controlled channel (access rights and
  integrity ensured at the third-party transport layer).
- **Supply chain**: pin the digests of the components embedded in the bundle; audit
  `VERSIONS.txt` against vulnerability advisories (CVE/GHSA).
- **Keys**: rotate keys and passphrase periodically; optionally separate signing and
  encryption keys.
- **Access**: restrict by ACL the `runtime/` directories, the keyring and the
  passphrase file to the service account only.
