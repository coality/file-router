# 14 — Analyse des risques

Registre des risques avec probabilité (P), impact (I) et criticité (P×I) sur une échelle
1–5, et mesures de mitigation. Voir aussi [10](10-security-policy.md), [09](09-error-handling.md),
[16](16-disaster-recovery.md).

## 1. Registre des risques

| ID | Risque | P | I | Crit. | Mitigation |
|----|--------|---|---|-------|------------|
| R01 | Perte de fichier (crash en cours de déplacement) | 2 | 5 | 10 | Renommage atomique + write-then-rename + réconciliation ; jamais de suppression avant publication confirmée |
| R02 | Publication partielle d'un fichier (lecture d'un fichier en cours d'écriture) | 2 | 4 | 8 | temp-puis-renommage ; contrôle de taille stable avant détection |
| R03 | Altération du payload en transit | 2 | 5 | 10 | `payload_file_hash` vérifié avant déchiffrement ; quarantaine |
| R04 | Altération du contenu métier | 1 | 5 | 5 | `clear_file_hash` après déchiffrement ; signature |
| R05 | Faux émetteur / usurpation | 2 | 5 | 10 | Signature obligatoire + signataires autorisés |
| R06 | Fuite de données sensibles | 2 | 5 | 10 | Chiffrement OpenPGP, permissions FS, secrets hors-config |
| R07 | Compromission de clé privée | 1 | 5 | 5 | Master key hors-ligne, sous-clés, rotation/révocation, coffre |
| R08 | Doublons (ré-émission, rejeu) | 3 | 3 | 9 | Index dédup FS, idempotence, politiques skip/overwrite |
| R09 | Verrou périmé bloquant un fichier | 2 | 3 | 6 | TTL + heartbeat + reaper ; contrôle de vivacité |
| R10 | Saturation disque (runtime/exchange) | 3 | 4 | 12 | Alerte disque, purge par rétention, backlog borné |
| R11 | Backlog non drainé (sous-dimensionnement) | 2 | 3 | 6 | Métriques `oldest_pending`, scaling des workers |
| R12 | Config erronée déployée | 2 | 4 | 8 | Validation par schéma, fail-fast, reload rejette l'invalide |
| R13 | Corruption de l'arborescence métier (collision de noms en entrant) | 2 | 4 | 8 | Restauration depuis metadata, politique de doublon, mkdir atomique |
| R14 | Indisponibilité du backend crypto (gpg) | 1 | 4 | 4 | Self-test au boot, fail-fast, doc prérequis |
| R15 | Crash répété / corruption de runtime | 1 | 4 | 4 | États finis récupérables, quarantaine, supervision |
| R16 | Cross-volume non atomique | 2 | 4 | 8 | Copie+fsync+rename ; purge des `*.partial` |
| R17 | Horloge non synchronisée (timestamps incohérents) | 2 | 2 | 4 | NTP requis ; `technical_id` (ULID) reste unique et ordonnable |
| R18 | Dépendance vulnérable (chaîne logicielle) | 2 | 4 | 8 | Versions figées, SBOM, scan CI ([15](15-versioning-upgrade.md)) |
| R19 | Volume de quarantaine non traité | 2 | 3 | 6 | Alerte `quarantine_current`, runbook, jamais auto-supprimé |
| R20 | Perte du trousseau de clés | 1 | 5 | 5 | Sauvegarde chiffrée hors-ligne, procédure de restauration |

## 2. Risques majeurs (criticité ≥ 9) — focus

- **R10 (disque, 12)** : risque opérationnel n°1. Mitigation = supervision proactive +
  purge automatique + dimensionnement documenté ([11](11-archival-retention.md)).
- **R01/R03/R05/R06 (10)** : couverts par les invariants de conception (atomicité,
  double-hash, signature, chiffrement). Aucun de ces risques ne doit pouvoir entraîner une
  perte/fuite silencieuse — toujours quarantaine + alerte.
- **R08 (9)** : doublons traités sans base via index FS et idempotence
  ([09 §5](09-error-handling.md)).

## 3. Risques résiduels acceptés

- Transport externe hors périmètre : FileRouter détecte la corruption (hash) mais ne garantit
  pas la livraison — responsabilité du mécanisme de transport.
- Disponibilité dépendante de l'OS/stockage sous-jacents (cluster/SAN hors périmètre).

## 4. Suivi

Les risques sont revus à chaque montée de version majeure et après tout incident
(post-mortem alimentant la table). Les métriques de [08](08-observability.md) fournissent les
indicateurs avancés (backlog, quarantaine, verrous périmés, échecs d'intégrité).
