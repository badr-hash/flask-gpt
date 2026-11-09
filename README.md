# FlaskGPT

Assistant conversationnel Flask en français, utilisant Groq et le SDK Python OpenAI.
Les sept fonctionnalités demandées sont répertoriées dans `to_do.text.txt`.

## Démarrer sous Windows

Ouvrir PowerShell dans ce dossier :

```powershell
.\start.ps1
```

Le script prépare l'environnement si nécessaire et lance l'application sur
**http://127.0.0.1:5000**. Python 3.10 ou supérieur est nécessaire.
Si PowerShell bloque les scripts, utiliser les commandes Python ci-dessous.

### Installation manuelle

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Ne copier `.env.example` que si `.env` n'existe pas encore.
Dans `.env`, renseigner la clé personnelle :

```dotenv
GROQ_API_KEY=votre_cle_groq
GROQ_MODEL=openai/gpt-oss-120b
PORT=5000
```

Puis lancer :

```powershell
.\.venv\Scripts\python.exe run.py
```

Après une modification de `.env`, arrêter le serveur avec Ctrl+C puis le relancer.
La clé reste côté serveur. Elle n'est ni envoyée au navigateur, ni incluse dans les exports.
Sans clé, l'interface, l'historique et les exports fonctionnent ; les demandes IA
affichent une instruction de configuration. Aucune réponse de démonstration n'est
présentée comme une vraie réponse IA.

## Utilisation

- **Nouvelle conversation** : ouvrir un nouveau fil sans effacer les précédents.
  Une réponse en cours dans l'ancien fil est annulée.
- **Historique à gauche** : sélectionner une conversation pour retrouver ses
  messages, sa spécialité et ses évaluations. Le titre est tiré du premier message
  ou du nom du document résumé. Les fils les plus récemment utilisés apparaissent
  en premier. La dernière conversation choisie reste sélectionnée après actualisation.
- **Supprimer une conversation** : cliquer sur sa corbeille et confirmer. Seul ce
  fil, ses messages, ses textes extraits et ses évaluations sont supprimés. Si le
  fil actif est supprimé, un autre est ouvert ; si c'était le dernier, un fil vide
  est créé. L'historique est aussi accessible sur mobile.
- **Effacer** : vider les messages du fil actuel tout en conservant sa place dans
  l'historique. Les autres conversations restent disponibles. Une réponse en cours
  est annulée et ne peut pas réintroduire les messages effacés.
- **Spécialité** : assistant général, Python, développement web, analyse de
  données, mathématiques ou rédaction et langues. Ce choix modifie réellement
  les instructions du modèle et reste enregistré après actualisation.
- **Niveau d'explication** : débutant, intermédiaire ou avancé. Le niveau est
  enregistré séparément pour chaque conversation. Une demande explicite de
  longueur ou de détail reste prioritaire.
- **Historique** : les échanges terminés sont enregistrés dans SQLite. Revenir
  depuis le même navigateur permet de retrouver la conversation, y compris après
  un redémarrage du serveur. Chaque session de navigateur possède son propre
  historique. Les demandes de chaque onglet restent liées au fil affiché, même si
  un autre onglet change de conversation.
- **Exporter** : télécharger en Markdown, texte ou JSON. Les exports comprennent
  les messages, les noms des fichiers joints et les évaluations.
- **Joindre un fichier** : sélectionner un PDF, DOCX, TXT, MD ou CSV, ajouter
  éventuellement une consigne et envoyer. Sans consigne, un résumé est demandé.
  Le texte extrait reste disponible pour les questions suivantes sur le document.
- **Évaluer** : sélectionner « Utile » ou « À améliorer » et, si souhaité, ajouter
  un commentaire. Cliquer à nouveau sur l'évaluation la retire. Les avis sont
  enregistrés et restaurés avec l'historique ; il s'agit d'évaluations humaines.
- **Préciser un avis** : sélectionner des motifs (informations incorrectes, réponse
  vague, trop longue, hors sujet ou références manquantes). Ces motifs sont
  conservés après actualisation et inclus dans les exports.
- **Vérifier sur le Web** : cocher cette option pour vérifier un fait public ou
  actuel avec le navigateur intégré de Groq. Seule la question actuelle est
  utilisée ; l'historique et les textes des fichiers joints sont exclus. L'option
  est désactivée lorsqu'un fichier est joint et se décoche après une réussite.
  Les pages réellement ouvertes apparaissent en liens dans la réponse et les exports.
- **Arrêter** : interrompt la réponse. Les échanges interrompus ou échoués ne
  sont pas ajoutés au contexte du modèle. La demande peut être renvoyée.
- Entrée envoie un message ; Maj+Entrée ajoute une nouvelle ligne.

## Fichiers et limites

```text
app.py                  Routes, sessions, flux JSON et exports
chat_service.py         Client Groq, spécialités, contexte et erreurs API
storage.py              Transactions SQLite, messages et évaluations
document_reader.py      Extraction et validation des documents
answer_quality.py       Instructions de qualité, niveaux et motifs de retour
evals/                  Cas de référence et rapports de comparaison des modèles
templates/index.html    Interface
static/css/style.css    Styles adaptatifs, sans compilation Tailwind
static/js/script.js     Chat, fichiers, évaluations et gestion des erreurs
static/vendor/          Markdown-it et DOMPurify, versions et licences locales
instance/chat.sqlite3   Données de l'application (créé automatiquement)
instance/chat.before-history.sqlite3  Sauvegarde automatique avant migration de l'ancien historique
instance/.session-secret  Signature persistante des sessions (créée automatiquement)
tests/                  Tests du backend, du SDK et du navigateur
```

Les fichiers sont limités à **5 Mo**, **40 000 caractères extraits** et, pour les
PDF, **50 pages**. Les PDF scannés sans texte nécessitent un OCR préalable.
Les PDF chiffrés, les documents vides, illisibles ou trop longs sont refusés avec
un message explicite. Les fichiers originaux ne sont pas conservés : seul leur
texte extrait est stocké avec la conversation. Le contenu des fichiers est
traité comme une source à analyser, jamais comme des instructions à exécuter.

Les nouvelles extractions PDF conservent les repères `[Page N]`. Les fichiers
Word/texte reçoivent des repères `[Extrait N]` ; aucune page Word n'est inventée.
Les anciens textes enregistrés sans pagination sont citables comme extraits.
Les instructions demandent des références aux faits importants et signalent les
informations absentes ; ces consignes ne remplacent pas la vérification des sources.

## Qualité des réponses

Les instructions `quality-v3` demandent une réponse directe, un détail proportionné,
au plus trois questions indispensables, le respect du niveau choisi et une
distinction claire entre faits vérifiables, hypothèses et données absentes.
La date du jour est fournie dans le fuseau Africa/Casablanca. Les anciennes
affirmations de l'assistant ne sont pas considérées comme des sources vérifiées.
Sans l'option Web, l'assistant n'effectue pas de recherche Internet. Il ne dispose
pas d'un exécuteur de code. La recherche Web consomme du quota Groq et peut prendre
plus de temps ; aucune réponse n'est enregistrée si le fournisseur ne renvoie pas
de pages sources consultables. Les citations sont des éléments à vérifier, pas
une garantie que chaque affirmation est correcte.
Les réponses vides ou tronquées ne sont pas enregistrées comme des échanges réussis.

Le modèle configuré est `openai/gpt-oss-120b`, retenu après comparaison avec
`openai/gpt-oss-20b`. Le benchmark, ses limites, les références et les réponses
complètes sont dans [evals/README.md](evals/README.md) et
[le rapport de comparaison](evals/results/latest.md).

```powershell
.\.venv\Scripts\python.exe evals/run_quality.py
```

Cette commande effectue de vrais appels Groq sur des cas synthétiques et consomme
du quota. Les tests `pytest` et le serveur de test du navigateur utilisent des
réponses simulées et ne consomment pas de crédit API.

Les messages sont limités à 8 000 caractères. Le contexte envoyé au modèle est
borné et conserve des paires complètes de questions/réponses récentes ; l'historique
complet reste dans la base et dans les exports. Une conversation très longue peut
donc nécessiter de rappeler un ancien détail.

Le serveur utilise Waitress et écoute uniquement sur l'adresse locale. Le débogueur
Flask est désactivé. Les requêtes de modification sont protégées par un jeton CSRF,
les sorties Markdown sont assainies et les accès aux messages sont limités à leur
session. Les bibliothèques du navigateur sont locales : aucun CDN n'est nécessaire.
L'appel au modèle nécessite une connexion Internet.

Ne supprimer `instance/.session-secret` que pour invalider toutes les sessions.
Conserver cette clé avec la base pour permettre aux navigateurs existants de retrouver
leur fil après un redémarrage. Le navigateur doit conserver son cookie de session.
Les extractions de documents sont incluses dans la base : effacer la conversation
supprime également ces données et les évaluations associées.

Au premier démarrage d'une version antérieure limitée à une seule conversation,
la base est migrée automatiquement. Les identifiants, messages, textes extraits,
spécialités et évaluations sont préservés. Une copie SQLite cohérente est créée
avant la migration dans `instance/chat.before-history.sqlite3`. Cette sauvegarde
contient les données antérieures ; elle n'est pas modifiée par les suppressions
ultérieures dans l'application.

## Vérifications

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Ces tests couvrent notamment le stockage, l'isolation des sessions, les exports,
les spécialités, les évaluations, les documents acceptés et refusés, les erreurs
de clé/quota/connexion/délai, les interruptions et l'effacement pendant un flux.
Le SDK OpenAI réel est également testé avec un transport HTTP simulé.
Ces tests ne consomment aucun crédit API et ne valident pas une clé Groq réelle.

Pour les tests du navigateur, installer Playwright dans un environnement Node
séparé, lancer `.\.venv\Scripts\python.exe tests/ui_server.py`, puis exécuter
`node tests/browser.cjs`. `PLAYWRIGHT_MODULE` et `CHROME_PATH` permettent de spécifier
un module Playwright et un navigateur déjà installés. Le serveur de test utilise
une base temporaire et des réponses simulées ; il ne remplace pas le serveur normal.

Sources de compatibilité :
[SDK Python OpenAI](https://developers.openai.com/api/reference/python),
[Groq](https://console.groq.com/docs/overview),
[envoi de fichiers Flask](https://flask.palletsprojects.com/en/stable/patterns/fileuploads/).
