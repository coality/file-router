# 13 — Guide d'exploitation

Runbook destiné au support et à l'exploitation. Toutes les opérations s'appuient sur le
système de fichiers et la CLI `filerouter` (aucune base de données).

## 1. Commandes CLI d'administration

| Commande | Effet |
|----------|-------|
| `filerouter status` | État du service, backlog, quarantaine, fraîcheur de réconciliation. |
| `filerouter health` | Self-test (config, crypto), code de retour pour sonde. |
| `filerouter validate-config <path>` | Valide un YAML sans démarrer. |
| `filerouter trace <technical_id>` | Reconstruit l'historique (audit + logs corrélés). |
| `filerouter list-quarantine` | Liste les items en `runtime/error/`. |
| `filerouter replay <technical_id>` | Rejoue un item en quarantaine. |
| `filerouter reconcile` | Force une réconciliation immédiate. |
| `filerouter run` | Lance la boucle de service au premier plan. |
| `filerouter doctor [--fix] [--yes]` | Diagnostic config/environnement (+ réparation). |
| `filerouter-doctor --config <…> [--fix] [--yes]` | Même diagnostic, outil dédié. |
| `filerouter reload` | Recharge la config (revalidation + swap atomique). |
| `filerouter keys list` | Liste les clés du trousseau et leurs epochs. |

> **Périmètre v1.0** : sont implémentées `validate-config`, `health`, `trace`,
> `list-quarantine`, `reconcile`, `run` et `doctor` (+ l'outil `filerouter-doctor`).
> Les commandes `status`, `replay`, `reload` et `keys list` sont décrites ici comme
> cible et seront ajoutées dans une version ultérieure.

### 1bis. `filerouter-doctor` — diagnostic & réparation

Anticipe les problèmes avant la mise en production. Contrôles : config (schéma +
cohérence), existence et **droits** des répertoires (`base_folders`, `exchange`,
`runtime`), `runtime`/`exchange` sur le **même volume**, backend cryptographique et
**présence des clés** (auto-test GnuPG, clés destinataire/signature, signataires
autorisés), règles de chiffrement/compression référençant des alias connus.

- **Tous les problèmes** sont listés sur la sortie standard ; chaque problème non
  réparable est accompagné d'une **solution claire adaptée Linux/Windows**
  (`gpg --import`, `chmod`/`chown` sous Linux, `icacls` sous Windows, même volume…).
- `--fix` : propose de corriger les problèmes sûrs (création de répertoires) en posant
  une question avant chaque correction.
- `--fix --yes` : **réparation automatique** sans aucune question. La config est
  re-diagnostiquée après réparation (code de sortie reflétant l'état final).
- Le doctor ne corrige jamais automatiquement ce qui touche à la sécurité (clés, droits).

## 2. Tâches courantes

### 2.1 Suivre un fichier
1. Récupérer le `technical_id` (nom technique ou logs).
2. `filerouter trace <technical_id>` → chronologie complète (DETECTED → … → terminal).
3. En cas d'erreur : l'événement `ERROR` indique `step`, `message`, `quarantine_path`.

### 2.2 Traiter la quarantaine
1. `filerouter list-quarantine`.
2. Pour chaque item : lire `runtime/error/<id>/error.json`.
3. Corriger la cause (clé, config, droits, espace disque…).
4. `filerouter replay <id>` ; vérifier l'aboutissement via `trace`.

### 2.3 Rechargement de configuration
1. `filerouter validate-config <new.yaml>`.
2. Remplacer le fichier de config.
3. `filerouter reload` (la config invalide est rejetée, l'ancienne reste active).

### 2.4 Rotation de clés
Voir [06 §4](06-encryption.md). Procédure : générer/publier la nouvelle sous-clé, période de
chevauchement, bascule de la règle, retrait de l'ancienne après drainage des flux.

## 3. Démarrage / arrêt

| Action | Windows | Linux |
|--------|---------|-------|
| Démarrer | `sc start FileRouterService` | `systemctl start filerouter` |
| Arrêter (propre) | `sc stop FileRouterService` | `systemctl stop filerouter` |
| Statut | `sc query FileRouterService` | `systemctl status filerouter` |

L'arrêt est **coopératif** : l'item en cours se termine, les verrous sont libérés, les logs
sont flushés. Un arrêt brutal est rattrapé par la réconciliation au redémarrage ([16](16-disaster-recovery.md)).

## 4. Diagnostic rapide

| Symptôme | Vérifier | Cause probable |
|----------|----------|----------------|
| Fichiers non détectés | inclusion/exclusion, droits, stabilité | règle d'exclusion, fichier encore en écriture |
| Backlog qui monte | workers, IO, verrous périmés | sous-dimensionnement, partage lent |
| Quarantaine en hausse | `error.json` par item | clé/signature, config, droits, disque |
| Aucune publication | espace disque, ACL exchange | disque plein, permissions |
| Échecs d'intégrité | flux security | corruption transport, altération |
| Service ne démarre pas | `validate-config`, self-test crypto | YAML invalide, trousseau/passphrase |

## 5. Bonnes pratiques d'exploitation

- Surveiller en continu `quarantine_current` (objectif : 0) et `oldest_pending_age`.
- Ne **jamais** supprimer manuellement un item de `processing/` sans `reconcile` (risque de
  doublon) ; préférer les commandes CLI.
- Sauvegarder régulièrement `runtime/audit/`, `keys/` et la config.
- Tester la rotation de clés en pré-production avant chaque échéance.
- Contrôler l'espace disque du volume `runtime`/`exchange` (alerte obligatoire).

## 6. Sauvegarde & restauration

| Élément | Sauvegarde | Restauration |
|---------|-----------|--------------|
| Config YAML | VCS + sauvegarde | redéploiement |
| Clés (`keys/`) | sauvegarde chiffrée hors-ligne | réimport dans `gnupg_home` |
| Audit (`runtime/audit/`) | sauvegarde régulière | copie en place (append-only) |
| Archive | selon politique | copie en place |

> `runtime/processing/`, `staging/`, `temp/`, `locks/` sont **volatils** : ils n'ont pas
> besoin d'être sauvegardés ; la réconciliation les reconstruit/nettoie au démarrage.
