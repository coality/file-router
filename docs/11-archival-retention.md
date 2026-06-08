# 11 — Archivage & rétention

## 1. Politique d'archivage des sources sortantes

À l'issue d'un traitement sortant réussi (`MOVED_TO_EXCHANGE_OUT`), la source métier est
traitée selon `archival.source_policy` :

| Politique | Comportement |
|-----------|--------------|
| `archive` | Déplacement atomique de la source vers `runtime/archive/<archive_layout>/<technical_id>__<original_filename>` ; événement `ARCHIVED`. |
| `delete` | Suppression de la source ; aucun événement `ARCHIVED`. |

```yaml
archival:
  source_policy: archive
  archive_layout: "%Y/%m/%d"      # ex. runtime/archive/2026/06/08/
```

- L'archivage permet le **retraitement** et l'**audit** ; la suppression convient aux flux où
  la source est déjà tracée ailleurs.
- L'archive conserve le `technical_id` dans le nom pour corrélation avec l'audit et les logs.

## 2. Données soumises à rétention

| Donnée | Emplacement | Paramètre | Défaut |
|--------|-------------|-----------|--------|
| Sources archivées | `runtime/archive/` | `retention.archive_days` | 30 |
| Audit par fichier | `runtime/audit/` | `retention.audit_days` | 365 |
| Logs (4 flux) | `logs/` | `retention.logs_days` | 90 |
| Quarantaine | `runtime/error/` | `retention.error_days` | 0 (jamais auto) |
| Dédup | `runtime/dedup/` | `retention.dedup_days` | = archive_days |

> L'audit a la rétention la plus longue car il constitue la **piste d'audit légale**. La
> quarantaine n'est jamais auto-purgée (action humaine requise).

## 3. Mécanisme de purge (sans base de données)

- **Balayage périodique** (`recovery.reconcile_interval` ou tâche dédiée) qui parcourt les
  répertoires concernés et supprime les fichiers dont l'âge (mtime ou date dans le chemin)
  dépasse le seuil.
- Purge **idempotente** et **interruptible** : suppression unitaire ; un crash en cours de
  purge n'a aucun effet de bord (relancée au cycle suivant).
- Les purges sont **auditées** dans le flux **admin** (nombre d'items, octets libérés, plus
  ancien conservé).
- Ordre de purge sous pression disque : logs tournés > archive > dédup. L'audit et la
  quarantaine ne sont jamais purgés par la pression disque (seulement par leur seuil de
  rétention explicite).

## 4. Conformité & exceptions

- Les seuils sont **par environnement** (un flux réglementé peut imposer `audit_days: 3650`).
- Une **mise sous séquestre** (legal hold) est réalisable en déplaçant les artefacts d'un
  `technical_id` vers un répertoire exclu de la purge (`runtime/hold/`), opération auditée.
- Aucune purge ne supprime un item encore référencé par un traitement en cours (verrou
  présent) : la purge ignore les `processing/`/`staging/` actifs.

## 5. Dimensionnement

La spec recommande de documenter, par environnement : volumétrie quotidienne moyenne/pic,
taille moyenne des fichiers, et d'en déduire l'espace nécessaire =
`Σ(rétention_jours × volume_quotidien)` pour archive + audit + logs, avec marge pour la
quarantaine et les pics. Une alerte disque (< seuil libre) est obligatoire
([08 — Supervision](08-observability.md)).
