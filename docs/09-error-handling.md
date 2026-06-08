# 09 — Gestion des erreurs & doublons

Principe directeur : **échec sûr, jamais de perte ni de publication partielle**. Au moindre
doute, l'item est mis en quarantaine avec son contexte, l'événement `ERROR` est audité, et
un opérateur décide du rejeu.

## 1. Taxonomie des erreurs

| Catégorie | Exemples | Transitoire ? | Traitement |
|-----------|----------|---------------|------------|
| **Transitoire IO** | fichier verrouillé par un tiers, partage indisponible, disque temporairement plein | Oui | retry borné avec backoff, puis quarantaine |
| **Intégrité** | hash payload/clair non concordant | Non | quarantaine + alerte sécurité |
| **Cryptographique** | clé absente, signature invalide, déchiffrement KO | Non (sauf clé manquante récupérable) | quarantaine + alerte sécurité |
| **Configuration** | alias inconnu, base_folder cible introuvable, motif de nommage invalide | Non | quarantaine ; souvent fail-fast au démarrage |
| **Données** | metadata absente/corrompue, paire incomplète, nom trop long | Non | quarantaine après `pair_grace_period` |
| **Système** | crash process, coupure courant, arrêt service | — | repris par la réconciliation ([16](16-disaster-recovery.md)) |

## 2. Stratégie de retry

```yaml
# (paramètres indicatifs, configurables)
retry:
  max_attempts: 5
  base_delay_seconds: 2
  backoff: exponential      # 2,4,8,16,32
  jitter: true
```
- Les retries ne s'appliquent **qu'aux erreurs transitoires** (IO). Les erreurs d'intégrité,
  crypto, config et données ne sont **pas** retriées (échec déterministe).
- Le compteur de tentatives est porté par l'audit (événements `ERROR` successifs avec
  `details.attempt`) — pas d'état en mémoire perdu au crash.
- À l'épuisement des tentatives → quarantaine.

## 3. Quarantaine

Structure d'un item en quarantaine :
```text
runtime/error/<technical_id>/
├── payload.<ext>           # ou fichier source selon l'étape
├── metadata.meta.json      # snapshot si disponible
└── error.json              # {step, exception_type, message, attempts, ts, context}
```
- **Jamais auto-supprimé** (`retention.error_days: 0` par défaut) : exige une décision
  humaine.
- L'audit du fichier conserve l'événement `ERROR` terminal avec `quarantine_path`.

## 4. Rejeu (replay)

Outil d'administration `filerouter replay <technical_id>` :
1. Relit `error.json` et la metadata.
2. Replace l'item dans `staging/` (sortant) ou `processing/` (entrant) avec le **même**
   `technical_id`.
3. Le pipeline reprend ; l'idempotence garantit l'absence de double publication.
4. Un événement d'audit `DETECTED`/`RECEIVED_*` de rejeu est ajouté (avec `details.replay:true`).

## 5. Gestion des doublons

Un doublon = un fichier dont le **même contenu** ou le **même `technical_id`** a déjà atteint
un état terminal.

### 5.1 Détection
- **Par `technical_id`** : si un `*.audit.json` existe déjà avec un événement terminal de
  succès, une réapparition est un doublon (cas typique : rejeu involontaire, ré-émission du
  transport).
- **Par contenu** : clé `clear_file_hash` + `base_folder_alias` + `relative_path`. Permet de
  repérer un même fichier détecté deux fois sous deux chemins/temporalités.

### 5.2 Politique
```yaml
duplicates:
  outbound_policy: skip      # skip | reprocess | error
  inbound_policy: skip       # skip | overwrite | error
  index: runtime/dedup       # index léger sur FS (fichiers marqueurs par hash)
```
- **Sortant** : un même contenu déjà routé est par défaut **ignoré** (`skip`, audité), évitant
  les ré-émissions.
- **Entrant** : une livraison dont le fichier cible existe déjà à l'identique (même
  `clear_file_hash`) est **ignorée** ; si le contenu diffère, `inbound_policy` décide
  (`overwrite` versionné, ou `error`/quarantaine pour arbitrage).
- **Index dédup sans base** : un répertoire `runtime/dedup/<hash[:2]>/<hash>` contient des
  fichiers marqueurs (technical_id + horodatage). Création atomique `O_EXCL` =
  premier-arrivé-gagne, purgé selon rétention. Aucune base de données.

### 5.3 Idempotence des livraisons entrantes
Le déplacement final vers le répertoire métier utilise `os.replace` ; relivrer le même
contenu réécrit un fichier identique (no-op observable). Pour conserver une version
divergente, la politique `overwrite` écrit `name (technical_id).ext` et audite le conflit.

## 6. Frontières d'erreur

- Chaque item est traité dans un **contexte isolé** : une erreur sur un fichier n'affecte
  jamais les autres.
- Une erreur **globale** (config invalide au rechargement, backend crypto KO) bascule le
  service en mode **dégradé/arrêt propre** plutôt que de traiter de façon incorrecte (échec
  sûr). L'admin est alerté ([08](08-observability.md)).
