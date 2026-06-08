# 10 — Politique de sécurité

## 1. Objectifs de sécurité

| Propriété | Mécanisme |
|-----------|-----------|
| **Confidentialité** | Chiffrement OpenPGP des fichiers sensibles ([06](06-encryption.md)) |
| **Intégrité** | Double empreinte SHA-256 (payload + clair) ([07](07-hashing.md)) |
| **Authenticité** | Signature OpenPGP + liste blanche de signataires |
| **Traçabilité** | Audit append-only par fichier + logs sécurité |
| **Non-répudiation** | Signature vérifiée et journalisée (signer_key_id) |
| **Disponibilité** | Reprise sur incident, échec sûr, supervision |

## 2. Modèle de menaces (STRIDE résumé)

| Menace | Scénario | Contre-mesure |
|--------|----------|---------------|
| **Spoofing** | Faux émetteur dépose un payload | Signature obligatoire + signataires autorisés (`require_signature_inbound`) |
| **Tampering** | Altération du payload en transit | `payload_file_hash` vérifié **avant** déchiffrement |
| **Tampering** | Altération du contenu métier | `clear_file_hash` vérifié après déchiffrement |
| **Repudiation** | Déni d'émission | Signature + audit + logs sécurité |
| **Information disclosure** | Lecture de fichiers sensibles au repos/en transit | Chiffrement OpenPGP, permissions FS, payload chiffré dans l'échange |
| **DoS** | Saturation par fichiers/quarantaine | Backlog borné, supervision, quarantaine isolée |
| **Elevation of privilege** | Compromission du compte de service | Moindre privilège, isolation du trousseau, passphrase hors-config |

## 3. Gestion des secrets

- **Aucun secret en clair dans le YAML.** Passphrases de clés privées fournies par variable
  d'environnement protégée, fichier à permissions restreintes hors VCS, ou coffre
  (DPAPI/Credential Manager sous Windows, secret systemd/coffre sous Linux).
- Trousseaux (`gnupg_home`) à accès restreint au seul compte de service.
- La master key OpenPGP reste **hors-ligne** ; seules les sous-clés de service sont déployées
  ([06 §3](06-encryption.md)).
- Rotation et révocation : voir [06 §4](06-encryption.md).

## 4. Contrôle d'accès filesystem

| Chemin | Accès |
|--------|-------|
| `runtime/`, `logs/`, `keys/` | Compte de service uniquement (RW), administrateurs (R) |
| `exchange_in` / `exchange_out` | Compte de service (RW) + agent de transport externe (RW) |
| `base_folders` | Compte de service (RW) + applications métier |
| Config YAML | Compte de service (R), administrateurs (RW) |

- Exécution sous un **compte de service dédié, non-administrateur**, au plus juste privilège.
- Sous Windows : ACL explicites ; service en *Log on as* compte géré (gMSA recommandé).
- Sous Linux : utilisateur système dédié, umask restrictif, `ProtectSystem`/`PrivateTmp`
  via systemd (voir [12](12-deployment.md)).

## 5. Sécurité des données en quarantaine

Les payloads en quarantaine peuvent être **chiffrés** (cas nominal) : ils restent
confidentiels. Les fichiers en clair éventuels (échec post-déchiffrement) héritent des
permissions restreintes de `runtime/error/` et sont soumis à la même politique d'accès.

## 6. Journalisation de sécurité

Le flux **security** ([08](08-observability.md)) consigne : chiffrements/déchiffrements,
résultats de vérification de signature (signer_key_id, validité), échecs d'intégrité, accès
clés, rotations. Ces logs sont à rétention longue et protégés en écriture (append-only,
rotation signée optionnelle).

## 7. Durcissement applicatif

- Validation stricte des entrées (metadata, noms, chemins) ; rejet des chemins absolus, des
  traversées `..`, des noms réservés.
- Aucune désérialisation dangereuse (JSON/YAML en mode sûr — `yaml.safe_load`).
- Pas d'exécution de contenu ; aucun appel système dérivé de données non fiables.
- Dépendances figées et auditées (SBOM, scan de vulnérabilités CI) ([15](15-versioning-upgrade.md)).
- Conformité : la double empreinte + signature + audit append-only répond aux exigences
  d'intégrité et de piste d'audit (ex. SOX/ISO 27001) sans base de données.

## 8. Réponse à incident

- Compromission de clé → révocation + rotation d'urgence + rechiffrement des flux concernés.
- Détection d'altération (intégrité/signature) → quarantaine automatique + alerte SOC +
  conservation de l'item pour analyse forensique (l'audit fournit la chronologie complète).
