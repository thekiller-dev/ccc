# Fixtures de benchmark CodeGraph

Quatre microprojets contrôlés sont décrits dans `expected.json`, avec les chemins source, les symboles attendus, les relations sémantiques attendues, les diagnostics attendus et les sites où aucune arête ne doit être inférée.

- `imports/` : imports relatifs, `baseUrl`/`paths`, `extends` local avec surcharge, résolution `index.ts`, réexport nommé, import circulaire, module absent, package externe et alias parent remplacé.
- `types_calls/` : classes, interfaces, héritage, implémentation, appels inter-fichiers et qualifiés, homonymes entre fichiers, overload valide, choix conditionnel ambigu et appel de méthode sur une instance construite localement.
- `react_jsx/` : deux composants TSX importés et une déclaration JSX minimale locale. L’import est mesuré; le lien de rendu JSX est signalé hors schéma, car CodeGraph 1.0 n’a pas de relation JSX/`RENDERS`.
- `robustness/` : cycle de `extends`, configuration JSONC imbriquée invalide, source syntaxiquement invalide, imports relatifs qui continuent de fonctionner, fichiers sensibles et répertoire `node_modules` exclus.

Lancer le benchmark depuis la racine du dépôt :

```bash
.venv/bin/python tests/benchmark_accuracy.py --iterations 7 --json-out /tmp/codegraph-benchmark.json
```

Le score ne porte que sur les faits étiquetés `IMPORTS`, `CALLS`, `EXTENDS` et `IMPLEMENTS`; les relations structurelles `CONTAINS`/`DEFINES` et la relation JSX hors schéma ne sont pas incluses dans précision/rappel. Le script imprime également les arêtes réellement obtenues, les écarts, les imports/appels non résolus, la stabilité, le schéma, la provenance, les exclusions et les temps observés. Les mesures temporelles décrivent uniquement la machine et l’environnement Python où la commande tourne.
