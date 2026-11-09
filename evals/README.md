# Évaluation de la qualité des réponses

Ce benchmark utilise 14 cas synthétiques avec des références rédigées à l'avance :
connaissance simple, calcul, code avec cas limite, information absente, résumé
avec citations, instruction malveillante dans un fichier, e-mails, absence de
recherche Web, niveaux d'explication, rappel du contexte, année actuelle et
correction d'une confusion de personne. L'identité de l'artiste est vérifiée
avec la [fiche de son agence](https://www.paquinentertainment.com/artist/el-grande-toto).
Le champ `{CURRENT_YEAR}` est remplacé par l'année actuelle de l'application.

## Lancer une comparaison réelle

Depuis la racine du projet, avec `GROQ_API_KEY` dans `.env` :

```powershell
.\.venv\Scripts\python.exe evals/run_quality.py
```

Les instructions initiales sont comparées aux instructions actuelles sur
`openai/gpt-oss-20b`, puis les instructions actuelles sont testées sur
`openai/gpt-oss-120b`. Ces appels consomment des tokens et du quota Groq.
Ils ne lisent pas les conversations de l'application : seuls les cas synthétiques
de `cases.json` sont envoyés, sans document personnel.

```powershell
# Comparaison rapide de trois cas :
.\.venv\Scripts\python.exe evals/run_quality.py --limit 3 --output evals/results/smoke.json

# Reprendre une exécution identique interrompue :
.\.venv\Scripts\python.exe evals/run_quality.py --resume

# Trois passages pour observer la variabilité :
.\.venv\Scripts\python.exe evals/run_quality.py --repeats 3 --output evals/results/repeated.json

# Réutiliser uniquement les réponses dont la requête complète est identique :
.\.venv\Scripts\python.exe evals/run_quality.py --reuse evals/results/latest.json --output evals/results/next.json

# Vérification Web du cas public d'identification :
.\.venv\Scripts\python.exe evals/run_quality.py --case correct_misidentified_artist --web-case correct_misidentified_artist --reuse evals/results/latest.json --output evals/results/web-check.json
```

Un rapport JSON et un rapport Markdown sont écrits après chaque réponse. La clé
API n'est pas incluse. Les réponses réutilisées sont identifiées par `reused_from`
et le SHA-256 du modèle, des messages et des paramètres de génération.

## Interprétation

- **Exactitude** : faits attendus, calcul, comportement de la petite fonction
  Python et absence d'invention ciblée.
- **Pertinence** : réponse à la demande et limitation des questions inutiles.
- **Clarté** : indicateurs de longueur et de format ; une relecture reste nécessaire.
- **Complétude** : éléments demandés et repères de source attendus.

Le pourcentage est la moyenne des critères satisfaits par cas. Il ne représente
pas la probabilité que toute réponse future soit correcte. Les citations
reconnaissent les espaces Unicode ; la présence d'un repère ne prouve pas que
chaque affirmation est soutenue. Les références et les réponses intégrales sont
conservées pour la revue manuelle.

La latence et les tokens d'entrée/sortie sont mesurés. Les délais peuvent inclure
une attente de quota. Aucun prix en dollars n'est déduit de ces chiffres.
La variante Web utilise le navigateur intégré de Groq et affiche les URL des
pages réellement ouvertes. Elle est évaluée séparément des modèles sans recherche.
Les réponses vides, tronquées et les appels en erreur échouent. Un premier passage
reste exploratoire : étendre les cas et répéter l'évaluation avant de généraliser.

Les motifs de retour permettent de repérer des familles de problèmes. Ils sont
stockés dans SQLite et inclus dans les exports. Les avis des utilisateurs ne sont
ni utilisés automatiquement comme vérité de référence, ni envoyés au benchmark.

Méthode inspirée de la documentation officielle OpenAI :
[évaluation](https://developers.openai.com/api/docs/guides/evaluation-best-practices),
[instructions explicites](https://developers.openai.com/api/docs/guides/prompt-engineering).
