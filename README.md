# LocalASR

LocalASR est une application Windows de transcription audio et vidéo avec
correction dans le navigateur. Ce projet personnel et expérimental est un
démonstrateur technique local présenté comme portfolio public consultable.

## Transcrire et corriger localement

Le moteur utilise **faster-whisper**, le modèle multilingue **small** et le calcul
**CPU / INT8**. **PyAV** décode les médias avec ses bibliothèques FFmpeg intégrées :
l'architecture actuelle ne lance aucun `ffmpeg.exe` externe. Français, anglais
et détection automatique de langue sont proposés, sans traduction.

L'interface locale propose un éditeur par segments horodatés, la réécoute bornée,
la navigation entre segments, la recherche, la pagination et la vitesse de lecture.
Les corrections sont enregistrées automatiquement. La transcription brute et le
texte corrigé restent distincts ; le brut est en lecture seule dans l'API, sans
être inviolable face à une modification directe sur disque.

Après relecture, l'utilisateur valide une version et génère un PDF avec ReportLab.
Les exports **PDF, TXT, SRT et JSON** sont conservés séparément. Une nouvelle
correction remet le projet en brouillon. Le mode d'essai limite le traitement aux
cinq premières minutes et marque ses PDF TEST.

Un petit dépassement de la fin du dernier segment produit par le moteur peut
être ramené à la fin réelle de l'audio, dans une limite de deux secondes, sans
suppression du texte. Les autres horodatages invalides sont refusés ;
[la règle et ses tests](docs/TESTING.md) précisent ce traitement.

## Local-first et runtime indépendant

Le serveur écoute sur `127.0.0.1` et les ressources de l'interface sont locales.
L'application attend un modèle déjà disponible sur disque, impose le chargement
local et n'effectue aucun téléchargement automatique. Son runtime indépendant
fait l'objet d'un inventaire et d'une autorisation propres à chaque installation.
Aucun runtime, modèle, média, transcription ou résultat privé n'est distribué ici.

Le fonctionnement hors ligne a été testé sur la machine de développement avec
le réseau physiquement coupé (Wi-Fi coupé et Ethernet débranché), selon la
confirmation de l'utilisateur. Il s'agit d'un retour d'essai humain, non vérifié
de manière indépendante. Les gardes réseau Python ne sont pas un
pare-feu système pour les bibliothèques natives. Une vérification offline réelle
reste nécessaire pour qualifier une nouvelle installation.

## Installation et utilisation

Cible actuelle : **Windows 64 bits, CPython 3.14.3**. La reconstruction sur une
machine vierge reste à qualifier. Le dépôt contient une procédure préparée, une
configuration exemple et un générateur d'inventaire en attente d'approbation ;
il ne contient pas encore de verrou d'installation validé.

Suivre [la procédure de reconstruction](docs/PUBLIC_REPRODUCIBILITY.md), qui
distingue acquisition, vérification, installation, autorisation et exécution.
Après préparation de l'environnement, double-cliquer sur **Start LocalASR.cmd**,
ou lancer :

```powershell
& '.\Start LocalASR.cmd'
```

Le lanceur retrouve le Python déjà configuré dans `runtime/independent/local.json`.
La variable `LOCALASR_PYTHON` reste une surcharge facultative ; le Python choisi
doit correspondre à la configuration autorisée.

Choisir un média local, lancer la transcription, relire et corriger les segments,
puis valider et exporter. Attendre « Enregistré » avant de fermer l'éditeur.
Fermer l'onglet ne termine pas le serveur :

```powershell
& '.\Start LocalASR.cmd' --stop --no-browser
```

`--data-dir 'C:\path\to\local-data'` sélectionne un dossier de données ; réutiliser
la même option pour les relancements et l'arrêt. Conserver les données hors
synchronisation cloud et ne pas exposer le serveur via proxy, tunnel ou réseau.

## Tests et observations

Les [tests publics](docs/TESTING.md) utilisent des fixtures synthétiques et la
bibliothèque standard. Ils couvrent sauvegarde, révisions, brut séparé, exports,
protection de la source, API locale, diagnostics et refus des runtimes non autorisés.
Ils n'exigent ni modèle ni package ASR et ne mesurent pas la précision linguistique.

La qualification historique sur la machine de développement a rapporté 51 tests
unitaires, 15 contrôles de formats/runtime et 31 contrôles de workflow réussis,
dont un parcours synthétique de 1 080 segments et un PDF de 96 pages. Ces résultats
proviennent d'une version antérieure au nettoyage public et, pour les contrôles
runtime/workflow, d'outils de qualification non inclus dans le dépôt. Ils ne
constituent pas une qualification de l'installation publique sur machine vierge.

Lors d'un test humain, l'utilisateur a observé **environ 30 corrections sur
environ 45 minutes**, principalement sur du vocabulaire technique, des acronymes
et des homophones. C'est une observation utilisateur, **pas un WER** ni une mesure
scientifique de précision.

## Limites et droits

Application personnelle, mono-utilisateur, une transcription à la fois. Pas de
diarisation ni d'attribution automatique des locuteurs. L'anglais sur parole réelle,
CUDA, les autres OS et la portabilité complète ne sont pas qualifiés. La qualité
dépend du média ; une relecture humaine reste nécessaire.

LocalASR n'est pas un dispositif médical. Aucune validation clinique, certification
de sécurité, compatibilité universelle ou précision formellement mesurée n'est
revendiquée.

**Aucune licence de projet n'est accordée pour le moment.** Le projet est présenté
comme un portfolio consultable, sans revendication de statut open source.
Les dépendances conservent leurs propres conditions : voir [les tiers](docs/THIRD_PARTY.md).
