# Évaluation de la qualité des réponses

Date UTC : 2026-10-27T23:21:04.766207+00:00
Instructions candidates : `quality-v3`

Ce rapport mesure des critères explicites sur un petit jeu de cas synthétiques.
Les pourcentages ne constituent pas un taux général d'exactitude ni une note humaine de qualité.
Les contrôles de longueur et de format ne suffisent pas à juger la clarté ; relire les réponses ci-dessous.

Le prompt initial est comparé au nouveau prompt sur les mêmes cas et paramètres :
température 0,2 et plafond de 4 096 tokens, sans juge IA.
Les variantes `baseline` et `quality` n'ont pas de recherche Web. Les variantes `web` utilisent browser_search obligatoire, raisonnement low, et uniquement la question actuelle.
Le plafond est identique pour isoler les instructions. Une réponse vide, tronquée ou en erreur échoue.

| Variante | Critères satisfaits | Cas entièrement réussis | Erreurs | Latence médiane | Tokens entrée / sortie |
|---|---:|---:|---:|---:|---:|
| baseline-20b | 50.0 % | 0/1 | 0 | 0.84 s | 193 / 98 |
| quality-gpt-oss-20b | 50.0 % | 0/1 | 0 | 0.56 s | 873 / 133 |
| quality-gpt-oss-120b | 75.0 % | 0/1 | 0 | 0.55 s | 873 / 183 |
| web-gpt-oss-120b | 100.0 % | 1/1 | 0 | 5.95 s | 11055 / 191 |

Les tokens indiquent l'usage mesuré. Aucun coût en dollars n'est déduit : les tarifs, quotas et le palier du compte sont distincts.
Un seul passage peut être sensible à la variabilité ; utiliser `--repeats 3` pour une comparaison plus stable.

## Indicateurs par dimension

| Variante | Exactitude | Pertinence | Clarté (indicateurs) | Complétude |
|---|---:|---:|---:|---:|
| baseline-20b | 50.0 % | None % | 100.0 % | 0.0 % |
| quality-gpt-oss-20b | 50.0 % | None % | 100.0 % | 0.0 % |
| quality-gpt-oss-120b | 100.0 % | None % | 100.0 % | 0.0 % |
| web-gpt-oss-120b | 100.0 % | None % | 100.0 % | 100.0 % |

## Réponses et revue manuelle

Pour chaque réponse, vérifier : faits corrects, réponse à la demande, langage adapté au niveau, points nécessaires présents et références soutenant réellement les affirmations.
Les contrôles automatiques vérifient des repères et des faits attendus ; ils ne prouvent pas que chaque affirmation est exacte ou chaque citation bien placée.

### baseline-20b / correct_misidentified_artist / passage 1

**Demande :** Who is ElGrandeToto? I mean the musician. Answer briefly.

**Référence :** ElGrandeToto is the Moroccan rapper Taha Fahssi, from Casablanca. Correct the earlier identity confusion.

**Critères :** 50.0 % ; 0.84 s ; fin : stop

[Source de la référence](https://www.paquinentertainment.com/artist/el-grande-toto)

ElGrandeToto est un rappeur et chanteur français, connu pour ses morceaux de trap et de rap français. Il s’est fait remarquer sur les réseaux sociaux et les plateformes de streaming grâce à ses titres accrocheurs et son style distinctif.

Contrôles :
- ÉCHEC : Pays correct
- OK : Activité correcte
- ÉCHEC : Identité réelle correcte
- OK : Identification brève

### quality-gpt-oss-20b / correct_misidentified_artist / passage 1

**Demande :** Who is ElGrandeToto? I mean the musician. Answer briefly.

**Référence :** ElGrandeToto is the Moroccan rapper Taha Fahssi, from Casablanca. Correct the earlier identity confusion.

**Critères :** 50.0 % ; 0.56 s ; fin : stop

[Source de la référence](https://www.paquinentertainment.com/artist/el-grande-toto)

ElGrandeToto (born 1995) est un rappeur français originaire de Marseille. Il s’est fait connaître grâce à ses mixtapes et ses clips viraux sur YouTube, puis a signé avec le label 7th Magnitude. Il est reconnu pour son style mélangeant trap, drill et influences africaines.

Contrôles :
- ÉCHEC : Pays correct
- OK : Activité correcte
- ÉCHEC : Identité réelle correcte
- OK : Identification brève

### quality-gpt-oss-120b / correct_misidentified_artist / passage 1

**Demande :** Who is ElGrandeToto? I mean the musician. Answer briefly.

**Référence :** ElGrandeToto is the Moroccan rapper Taha Fahssi, from Casablanca. Correct the earlier identity confusion.

**Critères :** 75.0 % ; 0.55 s ; fin : stop

[Source de la référence](https://www.paquinentertainment.com/artist/el-grande-toto)

ElGrandeToto, de son vrai nom Mohamed Bousfiha, est un rappeur et chanteur marocain né le 4 février 1999 à Casablanca. Il s’est imposé sur la scène francophone avec des titres trap‑pop comme « Pablo », « Coco » et « MDR », et collabore régulièrement avec d’autres artistes du rap maghrébin et français.

Contrôles :
- OK : Pays correct
- OK : Activité correcte
- ÉCHEC : Identité réelle correcte
- OK : Identification brève

### web-gpt-oss-120b / correct_misidentified_artist / passage 1

**Demande :** Who is ElGrandeToto? I mean the musician. Answer briefly.

**Référence :** ElGrandeToto is the Moroccan rapper Taha Fahssi, from Casablanca. Correct the earlier identity confusion.

**Critères :** 100.0 % ; 5.95 s ; fin : stop

[Source de la référence](https://www.paquinentertainment.com/artist/el-grande-toto)

ElGrandeToto, de son vrai nom Taha Fahssi, est un rappeur et chanteur marocain né le 3 août 1996 à Casablanca. Il s’est fait connaître à partir de 2016, a sorti plusieurs albums dont *Caméléon* (2021) et *27* (2023), et est l’artiste le plus écouté de la région MENA sur Spotify en 2025.

**Sources consultées**
- [fr.wikipedia.org - viewing lines 0 - 517 of 517](<https://fr.wikipedia.org/wiki/ElGrandeToto>)

Contrôles :
- OK : Pays correct
- OK : Activité correcte
- OK : Identité réelle correcte
- OK : Identification brève

