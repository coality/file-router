# FileRouter — Spécification technique

FileRouter est un **routeur de fichiers local, sans réseau**, destiné aux environnements
d'entreprise. Il détecte des fichiers dans des répertoires métier, calcule des métadonnées
et des empreintes SHA-256, chiffre/signe éventuellement les fichiers via OpenPGP, les
renomme avec un nom technique configurable, puis les déplace à travers des répertoires
d'échange **plats** `exchange_out` / `exchange_in`. Côté réception, il valide, déchiffre,
restaure le nom d'origine et reconstruit l'arborescence métier de profondeur illimitée.

> **Aucune base de données.** Tout l'état réside sur le système de fichiers : fichiers
> metadata, fichiers d'audit, fichiers de verrouillage et répertoires techniques.

## Ordre de lecture

| # | Document | Sujet |
|---|----------|-------|
| 00 | [Vue d'ensemble](00-overview.md) | Contexte, objectifs, périmètre, glossaire, principes de conception |
| 01 | [Architecture](01-architecture.md) | Conception hexagonale, diagrammes de composants |
| 02 | [Flux](02-flows.md) | Diagrammes de flux et de séquence sortant/entrant |
| 03 | [Gestion d'état](03-state-management.md) | `runtime/`, machine à états, atomicité, verrouillage, reprise |
| 04 | [Formats de données](04-data-formats.md) | Metadata JSON, audit JSON, convention de nommage |
| 05 | [Configuration](05-configuration.md) | Schéma YAML complet |
| 06 | [Chiffrement](06-encryption.md) | Architecture OpenPGP, gestion/rotation des clés, signature |
| 07 | [Empreintes](07-hashing.md) | Hash SHA-256 clair/payload et ordre de validation |
| 08 | [Observabilité](08-observability.md) | Logs, métriques, politique de supervision |
| 09 | [Gestion des erreurs](09-error-handling.md) | Taxonomie d'erreurs, reprises, doublons |
| 10 | [Politique de sécurité](10-security-policy.md) | Modèle de menaces, durcissement |
| 11 | [Archivage & rétention](11-archival-retention.md) | Politique d'archivage, rétention |
| 12 | [Déploiement](12-deployment.md) | Multi-plateforme, service Windows, systemd Linux |
| 13 | [Guide d'exploitation](13-operations-guide.md) | Runbook pour le support/l'exploitation |
| 14 | [Analyse des risques](14-risk-analysis.md) | Registre des risques |
| 15 | [Versionnement & montée de version](15-versioning-upgrade.md) | Stratégie de migration et d'upgrade |
| 16 | [Reprise après incident](16-disaster-recovery.md) | Stratégie de reprise |
| 17 | [Structure du projet](17-project-structure.md) | Arborescence Python + description par module |
| 18 | [Stratégie de tests](18-testing-strategy.md) | Toutes les catégories de tests |

### Artefacts vérifiables par machine

- Schémas : [`schemas/metadata.schema.json`](../schemas/metadata.schema.json),
  [`schemas/audit.schema.json`](../schemas/audit.schema.json),
  [`schemas/config.schema.json`](../schemas/config.schema.json)
- Exemples : [`examples/config.example.yaml`](../examples/config.example.yaml),
  [`examples/PAYMENT_OUT_20260608T120000_ABC123.meta.json`](../examples/PAYMENT_OUT_20260608T120000_ABC123.meta.json),
  [`examples/ABC123.audit.json`](../examples/ABC123.audit.json)

## Plateforme cible

- Windows Server 2019+ (cible principale, service natif via pywin32) **et** Linux (systemd).
- Python 3.12+.
- Le cœur portable ne contient aucun code spécifique à l'OS ; les spécificités sont isolées
  dans des adaptateurs.

## Statut

Spécification v1.0 — conception seule, aucune implémentation dans ce livrable.
