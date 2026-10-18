# Dépendances et notices tierces

Le projet ne distribue pas de licence pour son propre code à ce stade. Cette
décision est distincte des droits attachés aux composants tiers.

Le périmètre public déclare des dépendances dans `requirements-candidate.txt`
et les importe depuis une installation séparée. Il n'embarque pas les distributions
de ces packages, leurs wheels, DLL, extensions natives, modèles ou polices.
L'inspiration du décodeur est précisée ci-dessous. Les fichiers de
`static/` ne contiennent pas de bibliothèque frontend tierce identifiée.

Métadonnées locales observées, sans vérification juridique ou de provenance en ligne :

| Dépendance | Déclaration locale |
|---|---|
| faster-whisper, CTranslate2 | MIT |
| PyAV | BSD-3-Clause |
| ReportLab | BSD |
| huggingface-hub | Apache-2.0 |
| NumPy | plusieurs licences, dont BSD-3-Clause |
| Pillow | MIT-CMU |

`app/decoder.py` est une réécriture inspirée du mécanisme de décodage audio de
[faster-whisper 1.2.1, `faster_whisper/audio.py`](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/audio.py),
projet SYSTRAN distribué sous
[licence MIT](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/LICENSE).
La contre-revue indépendante n'a pas identifié de copie textuelle démontrée.
Cette attribution reconnaît cette inspiration ; elle ne place pas le code
LocalASR sous licence MIT. Aucun nouveau code upstream n'a été copié et aucune
notice copyright/licence existante n'a été retirée.

Les DLL FFmpeg/codecs, le modèle small, Python, les dépendances transitives et la
police Arial doivent être examinés séparément lors de l'acquisition. La licence
déclarée par PyAV ne suffit pas à qualifier toutes ses bibliothèques embarquées.
Ne pas recopier la police Windows dans le dépôt. Une future redistribution de
code ou de binaires tiers imposerait une nouvelle revue des notices et obligations.
