# Two-instance demo on a single machine (Site A → Site B)

This folder lets you run a realistic **two-site** FileRouter flow on **one** machine:

- **Site A** (`siteA.config.yaml`) is the *sender* (`role: outbound`).
- **Site B** (`siteB.config.yaml`) is the *receiver* (`role: inbound`).
- `transport.ps1` plays the **external transport** FileRouter does not do: it moves
  each `payload + .meta.json` pair from Site A's `exchange_out` to Site B's
  `exchange_in`.

Both sites share the **same alias** `BIZ` but map it to **different physical paths**
(`C:\SiteA\business` vs `C:\SiteB\business`) — exactly the multi-server model where
only the alias travels.

## Quick start (PowerShell, FileRouter installed in a venv)

```powershell
# 1. Diagnose + create every directory for both sites (no questions)
filerouter-doctor --config docs\examples\two-instance\siteA.config.yaml --fix --yes
filerouter-doctor --config docs\examples\two-instance\siteB.config.yaml --fix --yes

# 2. Start the two instances, each in its own terminal
filerouter --config docs\examples\two-instance\siteA.config.yaml run   # terminal 1
filerouter --config docs\examples\two-instance\siteB.config.yaml run   # terminal 2

# 3. Start the transport loop in a third terminal
.\docs\examples\two-instance\transport.ps1

# 4. Drop a file into Site A's business tree and watch it arrive at Site B
New-Item -ItemType Directory -Force C:\SiteA\business\clients\2026 | Out-Null
"id;amount`n1;100" | Set-Content C:\SiteA\business\clients\2026\test.csv
#   → appears in C:\SiteA\exchange_out, transported to C:\SiteB\exchange_in,
#     then rebuilt at C:\SiteB\business\clients\2026\test.csv
```

## Running both as native Windows services (optional)

Each instance becomes its own service with a unique name and its own config:

```powershell
python -m filerouter.service.windows install --instance siteA --config C:\path\to\siteA.config.yaml
python -m filerouter.service.windows install --instance siteB --config C:\path\to\siteB.config.yaml
python -m filerouter.service.windows start --instance siteA
python -m filerouter.service.windows start --instance siteB
```

This creates the services `FileRouter_siteA` and `FileRouter_siteB`, each reading its
config from `FILEROUTER_CONFIG_SITEA` / `FILEROUTER_CONFIG_SITEB`. See
[docs/fr/12-deployment.md](../../fr/12-deployment.md) (FR) /
[docs/en/12-deployment.md](../../en/12-deployment.md) (EN).

## Add encryption later

Switch `encryption.backend` to `gnupg` on **both** sites, add a `rules` block on the
sender and import the matching keys into each site's `gnupg_home`
(see [key generation](../../fr/06-encryption.md)). The sender encrypts with the
recipient's public key; the receiver decrypts with the recipient's private key.
