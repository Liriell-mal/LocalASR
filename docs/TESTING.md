# Tests publics

Les tests unitaires ne chargent aucun modèle ni runtime ASR. Ils utilisent la
bibliothèque standard de Python et des données synthétiques créées dans des
dossiers temporaires propres aux tests. Le lanceur de tests refuse les accès aux
dossiers privés du dépôt (`data`, `runtime`, `test-runs`) et aux configurations
locales. Les requêtes HTTP des tests restent sur la boucle locale.

Avec un CPython 3.14.3 Windows déjà installé et autorisé :

```powershell
& 'C:\path\to\python.exe' -I -B -S .\tests\run_tests.py
```

Ne pas créer ni exécuter un nouvel environnement sans l'autorisation applicable.
Les fixtures modèle sont des marqueurs factices : elles ne sont jamais chargées
par faster-whisper. Le moteur est remplacé en mémoire dans les tests du worker ;
les PDF unitaires sont également factices.

| Fichier | Couverture |
|---|---|
| `test_app.py` | stockage, révisions, exports, source, API et restrictions runtime |
| `test_diagnostics.py` | erreurs expurgées, absence de fuite de texte synthétique |
| `test_runtime_selection.py` | runtime indépendant, absence de repli, refus d'autorisation |
| `test_workflow.py` | persistance, réouverture, brut, lecture audio HTTP et offline logiciel |
| `test_public_setup.py` | inventaire en attente, conservation des fichiers, prérequis et alias de profil |
| `test_launcher.py` | lancement Windows sans variable d'environnement, arguments, configuration invalide |
| `test_asr_timing.py` | bornage limité de la fin du dernier segment ASR, conservation du texte, refus des autres anomalies |

`support.py` fournit une configuration éphémère ; `run_tests.py` est l'entrée
recommandée pour bénéficier du garde d'accès. Les tests sont destinés à Windows
car la protection des sources et le préflight utilisent ses APIs et polices.

Après acquisition et autorisation d'un environnement propre, la qualification
d'intégration doit encore vérifier : santé statique, inférence réelle sur un
média synthétique, édition/autosave/réouverture, PDF réel et session avec Wi-Fi
coupé/Ethernet débranché. Ne pas utiliser de données personnelles pour cette recette.
Le succès unitaire ne remplace ni ces contrôles ni une mesure de précision ASR.

À la réception du résultat ASR, seule la fin du dernier segment peut être
ramenée à la durée audio décodée, si son début est dans l'audio et si le
dépassement ne dépasse pas deux secondes. L'ajustement et la valeur d'origine
sont enregistrés dans les métadonnées ; aucun segment ni texte n'est supprimé.
Les dépassements plus grands, segments entièrement hors audio, inversions et
retours en arrière restent refusés. Cette règle ne s'applique pas aux corrections
manuelles : les horodatages enregistrés restent protégés contre leur modification.

Le plafond de **2,0 secondes incluses** est un choix applicatif conservateur pour
un dépassement terminal observé, pas une garantie de précision du moteur ni une
tolérance générale. Le stockage exige ensuite `0 <= start <= end <= durée` et
des débuts non décroissants : aucun dépassement intérieur n'est autorisé, même
inférieur à 0,1 seconde. La durée audio, les débuts, le texte et les autres champs
du segment restent inchangés ; seule une borne située après la fin audio est réduite.

Le brut applicatif est enregistré après cette normalisation ; la borne de fin
produite initialement par le moteur est conservée dans `asr_timestamp_adjustment`.
Les corrections de texte et exports ultérieurs ne modifient pas ce brut. Les
tests d'export comparent les bornes SRT/JSON, le texte TXT et l'instantané envoyé
au générateur PDF. Le test du PDF unitaire reste factice ; la recette avec le
runtime approuvé doit également vérifier une génération PDF réelle.
