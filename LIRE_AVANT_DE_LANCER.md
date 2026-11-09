# FlaskGPT — Dossier de remise

Application Flask de conversation avec une IA, interface en français et stockage SQLite.

## Démarrage rapide sous Windows

1. Extraire entièrement l'archive et ouvrir le dossier `FlaskGPT`.
2. Ouvrir PowerShell dans ce dossier et lancer `./start.ps1`.
3. Ouvrir http://127.0.0.1:5000 dans un navigateur.
4. Pour activer les réponses IA, renseigner sa propre clé dans le fichier `.env`
   créé par le script : `GROQ_API_KEY=...`, puis redémarrer le serveur avec Ctrl+C
   et `./start.ps1`.

Python 3.10 ou supérieur est nécessaire ; la version utilisée pour les vérifications
est Python 3.12. Une connexion Internet est nécessaire à l'installation des
dépendances et aux appels Groq. Node.js et une compilation CSS ne sont pas
nécessaires pour utiliser l'application : les bibliothèques du navigateur sont incluses.

Si PowerShell bloque le script, utiliser l'installation manuelle du `README.md`.
Sur macOS ou Linux :

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# Renseigner GROQ_API_KEY dans .env.
.venv/bin/python run.py
```

Une autre application peut déjà occuper le port 5000. Dans ce cas, renseigner par
exemple `PORT=5001` dans `.env`, redémarrer et ouvrir http://127.0.0.1:5001.

## Fonctionnalités demandées

| Élément du sujet | Réalisation |
|---|---|
| Effacer la conversation | Bouton « Effacer » avec confirmation ; messages et évaluations supprimés |
| Choisir une spécialité | Menu avec six domaines, dont la programmation Python |
| Stocker les échanges | Base SQLite créée automatiquement, avec messages et évaluations |
| Exporter la conversation | Téléchargement TXT, Markdown ou JSON |
| Insérer un fichier et le résumer | PDF, DOCX, TXT, MD et CSV ; consigne de résumé facultative |
| Gérer les erreurs | Clé absente/invalide, quotas, connexion, délai, fichier illisible et flux interrompu |
| Évaluer les réponses | Utile / À améliorer, motifs précis et commentaire facultatif |

Ajouts : historique de plusieurs conversations, sélection et suppression d'un fil,
niveaux débutant/intermédiaire/avancé, références de pages ou d'extraits, date
actuelle et recherche Web facultative avec liens vers les pages consultées.

Les anciennes conversations sont retrouvées dans le même navigateur après
redémarrage du serveur. Une nouvelle conversation conserve les précédentes.
La recherche Web utilise uniquement la question courante ; elle exclut
l'historique et les fichiers joints et consomme du quota Groq.

## Contenu de l'archive

- Code Python, interface HTML/CSS/JavaScript et bibliothèques locales avec licences.
- Instructions détaillées dans `README.md` et dépendances dans `requirements.txt`.
- Versions effectivement utilisées dans `requirements-tested.txt` (Python 3.12).
- Liste des tâches terminées dans `to_do.text.txt`.
- Tests dans `tests/` et benchmark documenté dans `evals/`.
- Rapports de comparaison et limites dans `evals/results/decision.md`.
- Exemple de document à résumer dans `examples/notes-a-resumer.txt`.

L'archive ne contient aucune clé API réelle, conversation personnelle, base de
données, signature de session, environnement virtuel ou cache. Les données et la
signature de session sont créées automatiquement au premier démarrage.

## Vérifier le projet

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Les tests automatisés utilisent des API simulées et ne consomment pas de quota.
Les rapports du benchmark enregistrent de vrais appels sur des cas synthétiques ;
relancer `evals/run_quality.py` utilise la clé et le quota du compte configuré.
Le modèle peut encore se tromper : les résultats et les échecs observés sont
conservés dans les rapports.
