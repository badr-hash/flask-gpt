# Décision après évaluation de la qualité

Modèle retenu : `openai/gpt-oss-120b`, avec les instructions `quality-v3` et une option de recherche Web explicite.

| Variante sans Web | Cas entièrement réussis | Moyenne des critères par cas | Exactitude ciblée |
|---|---:|---:|---:|
| baseline-20b | 8/14 | 82.1 % | 95.2 % |
| quality-gpt-oss-20b | 13/14 | 96.4 % | 95.2 % |
| quality-gpt-oss-120b | 12/14 | 96.4 % | 100.0 % |

Les deux modèles améliorés restent faillibles. Dans ce jeu élargi, le 120b a dépassé une limite de longueur et a donné un vrai nom erroné pour un artiste. Le 20b a également échoué à identifier correctement cet artiste. Les échecs sont conservés dans le rapport : aucune note parfaite générale n’est revendiquée.

La première itération complète (quality-v2) avait donné 12/12 cas réussis au 120b et 11/12 au 20b. Sur trois répétitions de trois cas sensibles avec quality-v2, le 120b a réussi 9/9 cas contre 7/9 pour le 20b. Ces répétitions concernent la version v2 ; elles ne sont pas présentées comme une nouvelle mesure de v3.

## Apport des sources Web

Une vérification supplémentaire a utilisé browser_search pour le cas public d’identification. La réponse Web du 120b a satisfait tous les critères de ce cas, avec le nom Taha Fahssi et des pages effectivement ouvertes. Ce résultat ne généralise pas à toutes les questions Web.

La recherche est donc proposée comme un mode distinct pour les faits actuels ou incertains. Elle transmet uniquement la question actuelle au fournisseur, sans réutiliser l’historique ni les fichiers. Les liens viennent des pages ouvertes par l’outil. Une absence de sources entraîne une erreur explicite.

Les chiffres mesurent un petit jeu de critères automatisés. Les indicateurs de longueur et de présence de références ne prouvent ni une clarté parfaite ni la vérité de chaque affirmation. Une relecture et un jeu plus large restent nécessaires.

Rapports : [14 cas sans Web](latest.md), [contrôle avec Web](web-check.md), [répétitions v2](stability.md), [première comparaison v2](prompt-v2.md).
