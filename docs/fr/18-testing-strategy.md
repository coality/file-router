# 18 — Stratégie de tests

Objectif : un maximum de couverture sur toutes les catégories demandées. Outils :
`pytest`, `pytest-cov`, `hypothesis` (property-based), `freezegun`/horloge injectée,
`pyfakefs` (FS factice) et un vrai FS temporaire pour les tests d'intégration.

## 1. Pyramide & organisation

```text
tests/
├── unit/            # cœur isolé via adaptateurs factices
├── integration/     # vrai FS temporaire + vrai gpg (clés de test)
├── load/            # débit/volumétrie/concurrence
├── security/        # crypto, signatures, intégrité, durcissement
├── recovery/        # crash/reprise, réconciliation, orphelins
├── regression/      # compatibilité metadata/audit/config inter-versions
├── fs_robustness/   # comportements filesystem extrêmes
├── fixtures/        # adaptateurs in-memory, jeux de clés, fabriques d'items
└── conftest.py
```

Cible de couverture : **≥ 90 %** sur `core/`, **≥ 80 %** global. Tous les tests exécutés en
CI sur Linux **et** Windows (matrice) pour valider la parité multi-plateforme.

## 2. Tests unitaires

Cœur testé sans IO ni crypto réelles (adaptateurs factices) :

- `naming` : rendu du motif, troncature/refus `max_length`, charset portable, noms réservés
  Windows, unicité `technical_id`, restauration du nom d'origine.
- `pathing` : identification base_folder par plus long préfixe, `relative_path` POSIX,
  profondeur illimitée, rejet des chemins absolus/`..`.
- `hashing` : vecteurs SHA-256 connus, streaming gros fichiers (mémoire constante),
  comparaison à temps constant.
- `metadata`/`audit` : invariants (encrypted⇒encryption, payload==clair si non chiffré),
  sérialisation, reconstruction d'historique, numéros de `seq`.
- `rules` : inclusion/exclusion (exclusion prioritaire), matching de règles de chiffrement.
- `state_machine` : seules les transitions légales sont permises.
- `dedup` : premier-arrivé-gagne, politiques skip/overwrite/error.
- **Property-based** (`hypothesis`) : pour tout chemin/à toute profondeur,
  `base_path / relative_path` reconstruit le chemin métier ; round-trip nom d'origine.

## 3. Tests d'intégration

Sur vrai FS temporaire, avec un vrai trousseau gpg de test :

- Pipeline **sortant** complet : détection → … → `exchange_out` + metadata + audit + archive.
- Pipeline **entrant** complet : `exchange_in` → validation → déchiffrement → métier.
- **Aller-retour** émetteur↔récepteur : un fichier traverse les deux pipelines et revient
  bit-à-bit identique, arborescence métier reconstruite à l'identique.
- Mapping inter-serveur : mêmes alias, chemins physiques différents.
- Backends crypto : mêmes tests sur `gnupg` **et** `pgpy`.
- Cross-volume (si applicable en CI) : copie+fsync+rename.

## 4. Tests de charge

- **Débit** : N milliers de fichiers (tailles variées : Ko → plusieurs Go) ; mesure latence
  bout-en-bout et débit.
- **Concurrence** : pool de workers saturé ; vérifier un-seul-écrivain-par-fichier (aucun
  double traitement) sous contention de verrous.
- **Gros fichiers** : mémoire bornée (streaming hash/crypto) — pas de pic mémoire avec la
  taille.
- **Backlog** : injection en rafale ; vérifier l'absence de perte et le drainage.
- **Endurance** (soak) : exécution prolongée ; absence de fuite (descripteurs, mémoire,
  verrous résiduels).

## 5. Tests de sécurité

- **Intégrité** : altérer le payload → échec `payload_file_hash` → quarantaine, jamais
  d'intégration. Idem altération post-déchiffrement → `clear_file_hash`.
- **Signature** : signature absente / invalide / signataire non autorisé → `ERROR` +
  quarantaine.
- **Confidentialité** : le payload dans l'échange est bien chiffré ; aucun clair ne fuit.
- **Ordre de validation** : prouver que le déchiffrement n'a pas lieu avant la validation du
  payload-hash.
- **Durcissement entrées** : metadata corrompue, chemins `..`/absolus, noms réservés, YAML
  malveillant (`safe_load`) → rejet propre.
- **Secrets** : aucune passphrase en clair dans la config ; permissions FS du trousseau.
- **Rotation/révocation** de clés : chevauchement d'epochs, révocation honorée.

## 6. Tests de reprise sur incident

Simulation de crash en injectant une panne **à chaque étape** du pipeline (kill du worker /
exception ciblée), puis réconciliation et vérification de l'invariant **ni perte ni double
publication** :

- Crash après chaque transition (avant/après chaque renommage atomique).
- Coupure pendant copie cross-volume → seul `*.partial`, purgé.
- Verrou périmé → repris par le reaper après TTL.
- Paire d'échange incomplète → quarantaine après grâce.
- Reprise depuis le dernier événement d'audit (réutilisation des sorties valides).
- Idempotence du **replay** : un item rejoué ne produit pas de doublon.
- RPO≈0 vérifié : tout fichier validé est soit livré soit rejouable, jamais perdu.

## 7. Tests de non-régression

- **Compatibilité de schéma** : une metadata `schema_version` antérieure est lue (tolérance
  ascendante) ; champs inconnus ignorés.
- **Ordre récepteurs-avant-émetteurs** : un récepteur de version N lit un format N-1.
- **Snapshots** des sorties (nom technique, metadata, séquence d'audit) pour figer le
  comportement ; tout écart est signalé.
- Jeu de **fichiers d'or** (golden files) pour les formats.

## 8. Tests de robustesse filesystem

- **Écritures partielles** : interruption en cours d'écriture → jamais de fichier partiel
  visible (temp+rename).
- **Fichier en cours d'écriture par un tiers** : non détecté tant que la taille n'est pas
  stable ; sonde d'ouverture exclusive (Windows).
- **Permissions** : refus de lecture/écriture/suppression → erreur gérée + quarantaine, pas
  de crash.
- **Disque plein** (`ENOSPC` simulé) : erreur transitoire → retry → quarantaine + alerte.
- **Noms extrêmes** : très longs, Unicode, caractères spéciaux, casse (NTFS insensible vs
  ext4 sensible).
- **Chemins profonds** : arborescence très profonde (profondeur illimitée) en entrant/sortant.
- **Renommage atomique** : prouver qu'après interruption, seul l'ancien **ou** le nouveau nom
  existe.
- **Cross-volume** : `os.replace` cross-device échoue proprement → chemin copie+rename.
- **Horloge** : tests avec horloge injectée (déterminisme des timestamps).

## 9. Intégration continue

- Matrice **Linux + Windows**, Python 3.12+.
- Étapes : lint (`ruff`), typage (`mypy`), tests unit+integration, couverture, scan de
  vulnérabilités des dépendances, validation des exemples contre les schémas
  ([README](README.md)).
- Les tests de charge/endurance tournent en pipeline planifié (nightly), pas à chaque commit.
