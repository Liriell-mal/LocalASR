# Reconstruire LocalASR sur Windows

La procédure est préparée ; **l'installation propre reste à qualifier**.
La consultation de métadonnées officielles ne vaut ni acquisition des packages,
ni vérification de leurs fichiers natifs, ni autorisation d'exécution.

## Spécification publique proposée

Le fichier `requirements-candidate.txt` contient les quatre imports tiers directs.
Le [verrou candidat](../requirements-lock-candidate.txt) fixe les 28 distributions
et SHA-256 des wheels envisagées, transitives comprises, pour Windows x64 et
CPython 3.14.3. Ces empreintes proviennent des métadonnées PyPI consultées ;
elles ne constituent pas une qualification ni une autorisation d'exécution.
Après qualification, les fichiers pourront perdre leur suffixe `candidate`.
Aucun packaging installable
`pyproject.toml` n'est nécessaire pour cette application lancée depuis ses sources.

Le résolveur doit parcourir normalement les métadonnées des dépendances ; ne pas
utiliser `--no-deps` pour masquer une dépendance gênante. Après résolution et revue,
le verrou complet avec hashes est l'entrée de l'installation reproductible.
Un inventaire d'installation existante ou un `pip freeze` isolé ne suffit pas.
Voir les [installations reproductibles documentées par pip](https://pip.pypa.io/en/stable/topics/repeatable-installs/).

## A. Dépendances directes de LocalASR

| Package | Version candidate actuelle | Import applicatif |
|---|---|---|
| faster-whisper | 1.2.1 | `app/worker.py` : WhisperModel |
| av (PyAV) | 18.1.0 | `app/decoder.py` : décodage et rééchantillonnage |
| numpy | 2.5.2 | `app/decoder.py` : signal float32 |
| reportlab | 5.0.1 | `app/pdf.py` : génération PDF |

PyAV et NumPy doivent être déclarés directement même s'ils apparaissent également
dans le graphe transitif. CTranslate2 est le moteur effectif, mais LocalASR ne
l'importe pas directement : sa version est fixée dans le verrou de qualification.
Les versions exactes ci-dessus reproduisent les versions locales observées, sans
revendiquer de compatibilité avec des versions non testées.

## B. Dépendances transitives

Métadonnées installées comparées aux métadonnées de versions sur PyPI. Les versions
suivantes sont celles envisagées pour le lot de qualification ; aucun changement
automatique de version n'est autorisé.

| Package | Version du lot | Parent / rôle |
|---|---|---|
| ctranslate2 | 4.8.1 | faster-whisper ; inférence CPU |
| huggingface-hub | 1.30.0 | faster-whisper et tokenizers ; accès modèle local/acquisition séparée |
| tokenizers | 0.23.2 | faster-whisper ; tokenisation |
| onnxruntime | 1.29.0 | dépendance déclarée de faster-whisper, même avec VAD désactivé |
| tqdm | 4.70.0 | faster-whisper et hub |
| pyyaml | 6.0.3 | CTranslate2 et hub |
| pillow | 12.3.0 | ReportLab |
| charset-normalizer | 3.5.1 | ReportLab |
| click | 8.4.2 | hub ; CLI tierce |
| filelock | 3.32.3 | hub |
| fsspec | 2026.7.0 | hub |
| httpx | 0.28.1 | hub |
| httpcore | 1.0.9 | httpx |
| anyio | 4.14.2 | httpx |
| h11 | 0.16.0 | httpcore |
| certifi | 2026.7.22 | httpx/httpcore |
| idna | 3.19 | httpx/anyio |
| packaging | 26.3 | hub/onnxruntime |
| flatbuffers | 25.12.19 | onnxruntime |
| protobuf | 7.35.1 | onnxruntime |
| typing-extensions | 4.16.0 | hub ; requis même si le marqueur propre à anyio est inactif |
| colorama | 0.4.6 | click/tqdm sur Windows |
| hf-xet | 1.6.0 | requis par les métadonnées hub sur Windows x64 ; absent du runtime applicatif historique |
| setuptools | 84.0.0 | requis par les métadonnées CTranslate2 ; absent du runtime applicatif historique |

Les contraintes déclarées incluent CTranslate2 `>=4,<5`, tokenizers `>=0.13,<1`,
ONNX Runtime `>=1.14,<2`, PyAV `>=11`, PyYAML `>=5.3,<7` via CTranslate2,
hub `>=0.21,<2` en combinant faster-whisper/tokenizers, httpx `>=0.23,<1`,
httpcore `==1.*` et protobuf `>=4.25.8`. Il ne faut pas élargir les bornes upstream
ni prétendre avoir qualifié toutes les versions qu'elles acceptent.
Sources : [faster-whisper 1.2.1](https://pypi.org/pypi/faster-whisper/1.2.1/json),
[CTranslate2 4.8.1](https://pypi.org/pypi/ctranslate2/4.8.1/json),
[tokenizers 0.23.2](https://pypi.org/pypi/tokenizers/0.23.2/json).

### Cas hf-xet et setuptools

`huggingface-hub 1.30.0` déclare `hf-xet>=1.5.2,<2` pour l'architecture AMD64,
sans condition d'extra. Ce n'est donc pas une dépendance optionnelle pour le
résolveur sur cette cible. `HF_HUB_DISABLE_XET=1` désactive son utilisation par
le hub, pas son installation par pip. LocalASR bloque en plus l'import `hf_xet`.
Source : [métadonnées hub](https://pypi.org/pypi/huggingface-hub/1.30.0/json) et
[variables officielles HF](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables).

La proposition conserve le graphe standard : installer hf-xet dans le nouvel
environnement **après approbation explicite**, puis vérifier qu'il n'est pas chargé
par LocalASR. Même distinction pour setuptools, requis par CTranslate2 mais
interdit par le chargeur applicatif. Les 26 packages du runtime historique sont
donc insuffisants pour représenter un environnement standard cohérent avec ces
métadonnées. `pip check` devra réussir sur le lot de 28 packages.

Refuser toute présence de hf-xet demanderait un autre choix de dépendances et
une nouvelle qualification ; aucun downgrade ou retrait de métadonnées n'est
effectué silencieusement. Les permissions historiques ne couvrent pas ces
nouvelles acquisitions, installations ni extensions natives.

## C. Options non retenues

Pas d'extra faster-whisper `conversion`/`dev`, ni Torch/Transformers, serveur HF,
extras cloud fsspec, extras ReportLab, CUDA ou programme FFmpeg externe.
Le modèle small est acquis séparément : ce n'est pas un package Python.
Le VAD est désactivé dans les profils ; cela n'annule pas la dépendance ONNX Runtime.

## D. Développement et tests

Les tests publics utilisent unittest, mocks, HTTP loopback et la bibliothèque
standard. Ils ne demandent ni pytest, ni Playwright, ni package ASR. Edge ou un
autre navigateur déjà installé sert à la recette manuelle, sans téléchargement
de navigateur. Pip est un outil d'installation, pas une dépendance de LocalASR ;
son origine et sa version doivent être recensées lors de la création du venv.

## Compatibilité ciblée

Windows x86-64, **CPython 3.14.3 standard avec GIL**, CPU INT8. Les métadonnées
Requires-Python du lot acceptent 3.14.3 ; PyPI propose des wheels compatibles :
`cp314-cp314-win_amd64`, wheels ABI stable `cp311-abi3` (PyAV), `cp310-abi3`
(tokenizers/protobuf), `cp38-abi3` (hf-xet), ou Python pur `*-none-any`.
Les wheels `cp314t` (free-threading), ARM64 et win32 ne sont pas retenues.
Exemples officiels : [NumPy](https://pypi.org/project/numpy/2.5.2/),
[PyAV](https://pypi.org/project/av/18.1.0/),
[CTranslate2](https://pypi.org/project/ctranslate2/4.8.1/).

La disponibilité d'une wheel ne prouve ni le chargement de ses DLL ni la réussite
de l'inférence. CPU, bibliothèques système et police Arial restent à vérifier
sur la cible. Pas de redistribution d'Arial ni promesse de portabilité universelle.

## Procédure préparée — arrêt avant acquisition/installation

1. Créer une copie des seuls fichiers publics dans un dossier de qualification
   neuf, isolé des données et du runtime historiques. Vérifier son manifeste.
2. Présenter chaque wheel : éditeur/projet upstream, version, URL PyPI et URL
   d'artefact exacte `files.pythonhosted.org`, nom, SHA-256 et rôle. Aucun paquet
   ne doit être exécuté pour vérifier sa provenance a posteriori.
3. Après accord d'acquisition uniquement : télécharger le lot, sans pip install,
   imports, hooks ou lancement. Refuser les redirections non approuvées. Hacher
   les fichiers, comparer aux SHA-256 publiés et inspecter statiquement les
   archives, notices, `.pth`, DLL/PYD et signatures. Toute signature absente,
   invalide ou inattendue impose l'exception explicite prévue par la politique.
4. Après accord distinct d'exécution : créer le venv avec le Python approuvé.
   `venv` peut exécuter ensurepip ; sa wheel embarquée doit également être revue.
5. Installer depuis le lot vérifié et un verrou complet avec hashes, hors réseau.
   Le verrou doit contenir toutes les transitives ; ne pas utiliser `--no-deps`.

Commandes indicatives, **non exécutées** pour la nouvelle installation :

```powershell
& 'C:\path\to\approved-python\python.exe' -I -B -m venv .venv
& '.\.venv\Scripts\python.exe' -I -B -m pip --isolated install --no-index --find-links .\wheelhouse --only-binary=:all: --require-hashes --no-cache-dir -r .\requirements-lock-candidate.txt
& '.\.venv\Scripts\python.exe' -I -B -m pip --isolated check
```

La recette propre doit acquérir séparément les quatre fichiers du modèle
[Systran/faster-whisper-small à la révision fixée](https://huggingface.co/Systran/faster-whisper-small/tree/536b0662742c02347bc0e980a01041f333bce120).
Révision : `536b0662742c02347bc0e980a01041f333bce120`.
Les URL d'acquisition sont construites exclusivement comme suit :

```text
https://huggingface.co/Systran/faster-whisper-small/resolve/536b0662742c02347bc0e980a01041f333bce120/config.json
https://huggingface.co/Systran/faster-whisper-small/resolve/536b0662742c02347bc0e980a01041f333bce120/model.bin
https://huggingface.co/Systran/faster-whisper-small/resolve/536b0662742c02347bc0e980a01041f333bce120/tokenizer.json
https://huggingface.co/Systran/faster-whisper-small/resolve/536b0662742c02347bc0e980a01041f333bce120/vocabulary.txt
```

Contrôles attendus pour cette révision, depuis les
[métadonnées officielles](https://huggingface.co/api/models/Systran/faster-whisper-small/revision/536b0662742c02347bc0e980a01041f333bce120?blobs=true) :

| Fichier | Octets | Empreinte publiée à vérifier |
|---|---:|---|
| config.json | 2370 | Git blob SHA-1 `e5047537059bd8f182d9ca64c470201585015187` |
| model.bin | 483546902 | LFS SHA-256 `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671` |
| tokenizer.json | 2203239 | Git blob SHA-1 `7818adb6de9fa3064d3ff81226fdd675be1f6344` |
| vocabulary.txt | 459861 | Git blob SHA-1 `c9074644d9d1205686f16d411564729461324b75` |

Un Git blob SHA-1 inclut l'en-tête `blob <taille>\0` avant les octets du fichier ;
ce n'est pas le SHA-1 simple du fichier. Calculer aussi un SHA-256 local pour
chaque fichier et le conserver dans l'inventaire. Ne pas confondre le pointeur
LFS avec les poids binaires du modèle.

Présenter les redirections avant accord : le contrôle d'en-têtes du 18 octobre
2026 a annoncé `us.aws.cdn.hf.co` pour les poids, et `huggingface.co` pour les
autres fichiers. Les URL signées du CDN expirent ; seul le contenu à la révision
fixée et aux empreintes attendues doit être accepté. Tout autre domaine demande
une nouvelle revue avant acquisition. Aucune copie du cache historique ne doit
être utilisée pour prétendre avoir qualifié cette acquisition propre.
Ne pas intégrer modèle/cache dans Git, ni télécharger automatiquement via l'application.

## Configuration, inventaire et lancement

Copier `models-config/example.json` vers `models-config/setup.local.json`
(ignoré), renseigner Python, site-packages, modèle et révision vérifiée.
Conserver CPU/INT8 et les profils transcribe. Après autorisation de l'interpréteur :

```powershell
& '.\.venv\Scripts\python.exe' -I -B -S .\scripts\prepare_installation.py --config .\models-config\setup.local.json
```

Cet outil refuse une sortie existante. Il écrit `runtime/independent/local.json`,
`inventory.json` et `approval.pending.json` (`approved: false`). Il n'importe
aucun package tiers, ne télécharge rien et n'accorde aucune autorisation.
Il hache environnement/modèle/interpréteur ; la bibliothèque standard Python et
les DLL système doivent aussi faire l'objet d'une revue séparée. Un hash seul
n'établit pas la provenance. Après revue et accord liés à l'inventaire exact,
créer localement `approval.json` ; ne pas réutiliser une autorisation d'un autre
environnement ni ignorer ses contrôles.

```powershell
& '.\.venv\Scripts\python.exe' -I -B -S .\scripts\check_health.py
& '.\.venv\Scripts\python.exe' -I -B -S .\tests\run_tests.py
& '.\Start LocalASR.cmd' --no-browser
```

Ouvrir `http://127.0.0.1:8765`. La santé statique ne constitue pas une inférence
réussie. `start.ps1` reste facultatif ; aucun contournement de politique PowerShell.
Le double-clic sur `Start LocalASR.cmd` utilise le champ `python` de la configuration
locale et ouvre le navigateur. `LOCALASR_PYTHON` est une surcharge facultative,
toujours soumise aux vérifications du runtime autorisé.

## Recette réelle et offline

Utiliser un média synthétique ou explicitement autorisé, sans données privées.
Vérifier transcription, horodatages, réécoute, correction, autosave, réouverture,
conservation du brut, validation humaine, PDF réel puis TXT/SRT/JSON.
Un silence synthétique teste le parcours mais pas une transcription linguistique ;
un bref enregistrement de phrases factices permet cette vérification fonctionnelle.

Après acquisition initiale, couper Wi-Fi et Ethernet, redémarrer et répéter le
parcours sans cache réseau requis. L'application conserve `HF_HUB_OFFLINE=1`,
`HF_HUB_DISABLE_TELEMETRY=1`, `HF_HUB_DISABLE_XET=1`, `TRANSFORMERS_OFFLINE=1`,
`DO_NOT_TRACK=1`, `PYTHONDONTWRITEBYTECODE=1` et `local_files_only=True`.
Vérifier l'absence d'import hf_xet et d'appel à FFmpeg externe. Le garde réseau
Python n'est pas un pare-feu système pour les DLL natives.

La session offline historique confirmée par l'utilisateur ne remplace pas cette
recette sur l'environnement neuf. Archiver les preuves techniques localement,
puis arrêter le serveur. Le rollback consiste à retirer uniquement les artefacts
du dossier neuf après vérification de son chemin ; aucun environnement historique,
modèle original, donnée privée, identité Git globale ou réglage Windows à modifier.
