# 08 — Observabilité

## 1. Flux de logs

Quatre flux distincts, tous au format **JSON Lines** (une ligne JSON par événement),
corrélables par `technical_id`.

| Flux | Contenu | Public |
|------|---------|--------|
| **technical** | Détail d'exécution : étapes de pipeline, temps, tailles, retries, IO. | Dev / N3 |
| **functional** | Vue métier : fichier détecté/routé/livré, alias, sites, direction. | Exploitation / métier |
| **security** | Crypto : chiffrement, signature, vérification, clé/epoch, échecs d'intégrité, accès. | RSSI / SOC |
| **admin** | Cycle de vie du service : start/stop, rechargement de config, réconciliation, purges. | Administration |

### Ligne de log type
```json
{"ts":"2026-06-08T12:00:00.560Z","level":"INFO","stream":"functional","event":"ROUTED_OUT","technical_id":"ABC123","base_folder_alias":"PAYMENT","direction":"OUT","target_site":"FRANKFURT","host":"SRV-A","msg":"file routed to exchange_out"}
```
Champs communs : `ts` (UTC ISO-8601 ms), `level`, `stream`, `event`, `technical_id`, `host`,
`msg`, plus champs spécifiques.

## 2. Corrélation

Le **`technical_id`** est la clé de corrélation transverse : logs (4 flux), metadata et audit
partagent cette clé. Reconstituer l'histoire d'un fichier =
`grep <technical_id>` sur les logs + lecture de `runtime/audit/<technical_id>.audit.json`.

> Logs ≠ audit. L'**audit** est la source de vérité durable et structurée par fichier (voir
> [04](04-data-formats.md)) ; les **logs** sont l'observabilité opérationnelle (volumétrie,
> diagnostic, sécurité) soumise à rotation/rétention.

## 3. Rotation, compression, rétention

- **Rotation** : par date (`daily`) ou par taille (`max_bytes`), `backup_count` configurable.
- **Compression** : gzip des fichiers tournés (`logging.compression`).
- **Rétention** : suppression au-delà de `retention.logs_days` (voir [11](11-archival-retention.md)).
- L'écriture des logs est **non bloquante** pour le pipeline (file d'attente bornée +
  écrivain dédié) ; en cas de saturation disque, le flux **security** est prioritaire et une
  alerte admin est levée.

## 4. Métriques (supervision)

Exposées via un fichier de métriques JSON rafraîchi périodiquement dans `runtime/` et/ou un
endpoint local optionnel (Prometheus textfile). Pas de dépendance réseau imposée.

| Métrique | Type | Usage |
|----------|------|-------|
| `files_processed_total{direction}` | compteur | débit |
| `files_error_total{step}` | compteur | taux d'erreur par étape |
| `quarantine_current` | jauge | items en `error/` (doit tendre vers 0) |
| `processing_backlog{queue}` | jauge | profondeur staging/exchange |
| `processing_duration_seconds` | histogramme | latence de bout en bout |
| `stale_locks_reclaimed_total` | compteur | signal de crashs |
| `last_reconcile_ts` | jauge | fraîcheur de la réconciliation |
| `oldest_pending_age_seconds` | jauge | détection de blocage |

## 5. Politique de supervision

| Signal | Seuil d'alerte | Sévérité | Action |
|--------|----------------|----------|--------|
| Service arrêté | absence de heartbeat admin | Critique | redémarrage / astreinte |
| `quarantine_current` > 0 | > 0 pendant N min | Majeure | analyse `error/`, rejeu |
| `files_error_total` (intégrité/signature) | toute occurrence | Critique (sécurité) | investigation SOC |
| `oldest_pending_age_seconds` | > seuil SLA | Majeure | blocage/backlog |
| Saturation disque (runtime/exchange) | < seuil libre | Critique | purge/extension |
| `last_reconcile_ts` trop ancien | > 2× intervalle | Mineure | vérifier la boucle |
| Échec de rotation de clé / clé expirée | proximité d'expiration | Majeure | rotation ([06](06-encryption.md)) |

### Health check
Un point de santé léger (fichier `runtime/health.json` ou exit code d'une commande
`filerouter health`) renvoie : état du service, backend crypto OK (self-test), backlog,
quarantaine, fraîcheur de réconciliation. Utilisable par une sonde de supervision externe.
