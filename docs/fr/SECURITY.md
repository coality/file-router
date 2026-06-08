# FileRouter — Document de sécurité

> Document **autoportant et généraliste**, destiné à une équipe sécurité /
> conformité **sans connaissance préalable** du projet. Il présente l'application,
> les données manipulées, puis l'ensemble des mesures de sécurité.

---

## 0. En une phrase

FileRouter est un **logiciel qui transfère des fichiers entre deux sites de façon
sécurisée**, en les chiffrant et en les signant, **sans base de données et sans
faire lui-même de réseau** : le transport réseau est assuré par un outil tiers
existant ; FileRouter gère la préparation, la protection, le contrôle d'intégrité
et la reconstruction des fichiers.

## 1. Ce que fait l'application

**Problème résolu.** Échanger des fichiers métier (ex. fichiers comptables `.csv`,
virements `.xml`) entre deux sites/serveurs, de façon fiable et confidentielle,
sans déployer de nouvelle infrastructure (ni base de données, ni service réseau
supplémentaire à exposer).

**Vue d'ensemble.**

```
 SITE A (émetteur)                 transport tiers              SITE B (récepteur)
 répertoire métier  --FileRouter-->  exchange_out  ==MFT/partage==>  exchange_in  --FileRouter-->  répertoire métier
 (ex. \\srv\compta)  détecte           (dépôt plat)  (hors périmètre)  (dépôt plat)   valide & livre  (ex. \\srv\compta)
                     hash, compresse,                                  vérifie hash,
                     chiffre, signe                                    déchiffre, vérifie
                                                                       signature, reconstruit
```

1. À l'**émission** : surveillance de **répertoires métier**, détection des nouveaux
   fichiers, empreinte SHA-256, **compression** puis **chiffrement + signature**
   (OpenPGP), renommage, dépôt dans `exchange_out`.
2. **Transport tiers** (MFT, réplication, partage) — **hors périmètre** — déplace
   les fichiers vers le site distant.
3. À la **réception** : lecture de `exchange_in`, **vérification empreinte +
   signature**, **déchiffrement**, décompression, **reconstruction de
   l'arborescence** d'origine et livraison.

**Ce que FileRouter NE fait PAS** : aucune connexion réseau, aucune base de données,
aucun port exposé. Tout son état tient dans des fichiers locaux.

## 2. Glossaire

| Terme | Signification |
|-------|---------------|
| **Répertoire métier** (`base_folder`) | Dossier surveillé contenant les fichiers à transférer. |
| **`exchange_out` / `exchange_in`** | Dossiers « boîte d'envoi / de réception » à la frontière avec le transport tiers. |
| **Payload** | Le fichier tel qu'il voyage (chiffré/compressé). |
| **Metadata** (`*.meta.json`) | Fiche technique accompagnant le payload (noms, chemins, empreintes) servant à reconstruire et auditer. |
| **`technical_id`** | Identifiant unique (ULID) par transfert ; clé de corrélation des journaux. |
| **OpenPGP** | Standard de chiffrement/signature (RFC 4880) ; moteurs `gnupg` ou `pgpy`. |
| **Quarantaine** | Dossier où sont isolés les fichiers en erreur, sans jamais les livrer « au doute ». |

## 3. Données manipulées

| Donnée | Sensibilité | Protection |
|--------|-------------|------------|
| Fichiers métier | Potentiellement sensible | Chiffrés + signés en transit ; empreintes vérifiées |
| Clé privée | Secret | Fichier/trousseau à accès restreint (compte de service) |
| Passphrase | Secret | Variable d'environnement ou fichier à ACL restreinte ; jamais dans la config |
| Métadonnées | Interne | Signées (intégrité du routage) |
| Journaux / audit | Interne | Sans secret ; exploitables par un SIEM |

## 4. Modèle de menace

- **Frontière de confiance** : `exchange_out`/`exchange_in` sont la limite avec le
  transport tiers ; selon la confiance accordée, le contenu de `exchange_in` peut
  être influencé par un attaquant disposant d'un accès au canal/partage.
- **Actifs** : confidentialité et intégrité des fichiers ; clé privée et passphrase ;
  **intégrité du routage** (destination de livraison).
- **Attaques considérées** : corruption en transit ; falsification des métadonnées
  (redirection) ; fichier non signé ou signé par un tiers non autorisé ; traversée
  de répertoire via des champs de métadonnées.

## 5. Mesures de sécurité

### 5.1 Secrets
- **Aucun secret dans la configuration** (YAML) : uniquement des **chemins** et des
  **identifiants de clés**.
- **Passphrase** : variable d'environnement `FILEROUTER_GPG_PASSPHRASE` (prioritaire)
  ou fichier `passphrase_file` à ACL restreinte au **compte de service**.
- **Clé privée** : fichier `private_key_file` (ACL restreinte) ou trousseau GnuPG.
- **Aucune écriture de secret dans les journaux** (uniquement identifiants de clés,
  empreintes, chemins).

```powershell
icacls C:\ProgramData\FileRouter\secrets\gpg.pass /inheritance:r
icacls C:\ProgramData\FileRouter\secrets\gpg.pass /grant "DOMAINE\svc_filerouter:R" "SYSTEM:R"
```

### 5.2 Chiffrement et signature
- Le contenu est **chiffré ET signé** (OpenPGP). Une seule paire de clés peut
  assurer chiffrement et signature (clé primaire de signature + sous-clé de
  chiffrement), ou des clés séparées selon la politique.

### 5.3 Intégrité et authenticité (réception)
Ordre de vérification **strict** :
1. empreinte du payload **avant tout déchiffrement** (anti-corruption) ;
2. déchiffrement ;
3. **signature du contenu** + contrôle que le **signataire est autorisé** (liste
   blanche) ;
4. empreinte du fichier en clair (intégrité bout-en-bout) ;
5. **signature des métadonnées** (signature détachée) : authentifie les champs de
   routage (chemin, nom, alias) pour empêcher la redirection d'un fichier signé.

### 5.4 Traversée de répertoire
Les champs de routage issus des métadonnées (`technical_id`, `relative_path`) sont
**strictement validés** (aucun `/`, `\`, ni `..`) avant toute utilisation comme
chemin de fichier.

### 5.5 Permissions
L'outil `filerouter-doctor` **signale** les problèmes de droits mais **ne modifie
jamais** les permissions (il peut uniquement créer un répertoire manquant — action
explicite et sûre).

### 5.6 Exécution sous compte de service (moindre privilège)
L'application tourne sous un **compte de service dédié** (ni administrateur, ni
système), avec accès limité aux seuls répertoires nécessaires. Recommandé : compte
de service géré (gMSA) sans mot de passe quand l'annuaire le permet.

### 5.7 Isolation des erreurs
Toute anomalie (empreinte, signature, déchiffrement, IO) **isole le fichier en
quarantaine** avec un rapport d'erreur ; **jamais de livraison « au doute »**.

### 5.8 Observabilité
Journal d'audit par fichier + journal de transferts lisible (date, sens, noms,
protections appliquées, empreinte), sans secret, exploitable par un SIEM.

## 6. Récapitulatif des contrôles

| Contrôle | Mécanisme |
|----------|-----------|
| Confidentialité | Chiffrement OpenPGP du contenu |
| Intégrité | Empreintes SHA-256 (payload + clair) vérifiées |
| Authenticité de l'émetteur | Signature du contenu + liste blanche de signataires |
| Intégrité du routage | Signature détachée des métadonnées |
| Protection des secrets | Hors configuration ; ACL ; jamais journalisés |
| Anti-traversée | Validation stricte des champs de chemin |
| Moindre privilège | Compte de service dédié |
| Confinement | Quarantaine des erreurs |
| Traçabilité | Audit par fichier + journal de transferts |

## 7. Recommandations de durcissement (déploiement)

- **Transport** : maintenir `exchange_in` comme un canal maîtrisé (droits d'accès et
  intégrité assurés au niveau du transport tiers).
- **Chaîne d'approvisionnement** : épingler les empreintes des composants embarqués
  dans le bundle ; auditer `VERSIONS.txt` contre les avis de vulnérabilité (CVE/GHSA).
- **Clés** : rotation périodique des clés et de la passphrase ; séparation possible
  des clés de signature et de chiffrement.
- **Accès** : restreindre par ACL les répertoires `runtime/`, le trousseau et le
  fichier de passphrase au seul compte de service.
