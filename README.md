# CodeGraph

CodeGraph est un outil local-first qui cartographie des projets JavaScript et TypeScript sans exécuter leur code. Un pipeline Python partagé par l’API et le CLI s’appuie sur Tree-sitter pour extraire les fichiers, symboles et relations, puis sur NetworkX pour construire un graphe orienté. Aucune requête vers un service externe ni aucun LLM n’est utilisé.

## Fonctionnalités

- Scan récursif des fichiers `.ts`, `.tsx`, `.js`, `.jsx`, `.mts`, `.cts`, `.mjs` et `.cjs`, avec lecture bornée et diagnostics tolérants.
- Extraction des fonctions, classes, interfaces, alias de types, imports, appels statiquement identifiables (dont les méthodes d’instances locales créées par un constructeur de classe unique), héritages et implémentations.
- Résolution prudente des imports relatifs internes, des alias `baseUrl`/`paths` des configurations `tsconfig.json`/`jsconfig.json` applicables (avec `extends` locaux confinés au projet) et des réexports nommés/`export *` en chaîne; extensions usuelles et fichiers `index` sont pris en compte, tandis que les cibles ambiguës ou non uniques restent non résolues.
- Graphe `networkx.MultiDiGraph` et export JSON versionné (schéma `1.0`) avec IDs stables, provenance, confiance et distinction entre observation directe et inférence.
- API FastAPI locale, commandes CLI, rapport Markdown et interface React/TypeScript avec exploration Cytoscape.js.
- Aucun endpoint de commande arbitraire. Le serveur API écoute sur `127.0.0.1` par défaut et n’accepte que les chemins confinés à sa racine autorisée.

## Prérequis et installation

- Python **3.13 ou ultérieur** et [uv](https://docs.astral.sh/uv/).
- Node.js **20.19+** ou **22.12+** et npm pour l’interface (Vite 8).

Depuis la racine du dépôt :

```bash
uv python install 3.13
uv sync
```

`uv sync` installe le paquet et le groupe de développement (`pytest`, Ruff et les dépendances de test). Le fichier `.python-version` fixe Python 3.13 pour les outils uv.

## CLI

Les quatre commandes utilisent le même moteur que l’API :

```bash
uv run codegraph scan examples/demo-ts
uv run codegraph stats examples/demo-ts
uv run codegraph export examples/demo-ts --output /tmp/demo-graph.json
uv run codegraph report examples/demo-ts --report-output /tmp/demo-report.md
```

`scan` écrit par défaut `PATH/.codegraph/graph.json` et `PATH/.codegraph/report.md`. Il accepte `--output`, `--report-output` et `--max-file-size BYTES` (1 000 000 octets par défaut). `export` et `report` acceptent respectivement `--output` et `--report-output`; `stats` imprime les statistiques JSON sur la sortie standard.

Pour afficher l’aide d’une commande :

```bash
uv run codegraph --help
uv run codegraph scan --help
```

## API locale

Lancer le serveur depuis le dossier qui contient les projets à analyser :

```bash
uv run codegraph-api
```

Par défaut, la racine autorisée est le dossier courant et l’API écoute sur `http://127.0.0.1:8000`. Pour définir une autre racine, fournir son chemin avant le démarrage :

```bash
CODEGRAPH_PROJECTS_ROOT="$HOME/projects" uv run codegraph-api
```

Dans ce cas, les requêtes de scan utilisent un chemin relatif à cette racine (ou un chemin absolu situé à l’intérieur). Les segments `..`, les chemins hors racine et les sorties de racine par lien symbolique sont refusés. `CODEGRAPH_API_HOST` et `CODEGRAPH_API_PORT` permettent de remplacer l’hôte et le port si nécessaire; l’hôte reste localhost par défaut.

| Méthode | Route | Description |
| --- | --- | --- |
| `GET` | `/health` | État du serveur et version du schéma |
| `POST` | `/api/scan` | Analyse d’un dossier autorisé, corps JSON `{"path":"demo-ts"}` |
| `GET` | `/api/projects/{project_id}/graph` | Graphe complet |
| `GET` | `/api/projects/{project_id}/stats` | Statistiques |
| `GET` | `/api/projects/{project_id}/nodes/{node_id}` | Détail d’un nœud |

Exemple :

```bash
curl -X POST http://127.0.0.1:8000/api/scan \
  -H 'Content-Type: application/json' \
  -d '{"path":"examples/demo-ts"}'
```

Les graphes servis par l’API sont conservés en mémoire et disparaissent à l’arrêt du processus. Pour archiver les résultats, utiliser le CLI et son export JSON/rapport Markdown.

## Interface web

Démarrer d’abord l’API, puis dans un autre terminal :

```bash
cd frontend
npm ci
npm run dev
```

Vite sert l’interface sur le port `5173` et relaie `/api` et `/health` vers l’API locale au port `8000`. Le navigateur n’appelle donc pas directement une adresse locale pour accéder à l’API. Dans l’interface, saisir le chemin relatif à la racine autorisée ou lancer la fixture réelle avec **Démo** / **Essayer la démo incluse**.

L’interface comprend :

- un état de connexion à l’API, les états de chargement, d’erreur et de projet vide;
- les statistiques de scan et les diagnostics;
- la recherche de nœuds, des filtres par type de nœud et de relation, et une liste de fichiers;
- le graphe Cytoscape interactif (déplacement, zoom, ajustement à la vue) et un panneau de propriétés/relations;
- le nettoyage de l’instance Cytoscape au démontage du composant.

Vérifications frontend :

```bash
npm run lint
npm run build
```

## Modèle de graphe et export

`graph.json` contient `schema_version`, `metadata`, `nodes` et `relations`. Chaque nœud fournit notamment `id`, `type`, `name`, `path`, `start_line`, `end_line` et `metadata`. Les IDs de fichier et de symbole dérivent du chemin relatif et du nom qualifié; ils ne dépendent pas de l’ordre du parcours. Un renommage ou un changement de portée peut donc changer l’ID correspondant.

Types de nœuds : `project`, `file`, `function`, `class`, `interface`, `type`, `module`.

Types de relations : `CONTAINS`, `IMPORTS`, `DEFINES`, `CALLS`, `EXTENDS`, `IMPLEMENTS`. Chaque relation comprend `source`, `target`, `provenance` (chemin, lignes, preuve et méthode), `confidence`, `certainty`, `origin` et `inferred`. Les déclarations extraites directement sont distinguées des relations inférées par résolution statique.

## Sécurité, périmètre et limites

- CodeGraph lit et parse les fichiers source sans les exécuter, sans interpréter de configuration comme du code et sans transmettre le contenu à un service externe. Avec Tree-sitter `0.26+`, les sources JSX/TSX passent par un processus natif isolé; un crash ou délai de ce worker est signalé pour les fichiers concernés au lieu d’arrêter l’analyse du projet.
- Les dépendances, répertoires de build/cache, fichiers sensibles (`.env`, motifs de secrets/clés privées) et marqueurs PEM sont exclus. Les liens symboliques ne sont pas suivis. La limite par défaut est de 1 000 000 octets par fichier; les erreurs de lecture, d’encodage et de syntaxe sont signalées sans interrompre les autres fichiers.
- Tree-sitter est temporairement contraint à la branche `0.25.x`: la version `0.26.0` a reproduit un SIGSEGV pendant l’extraction de gros fichiers TSX. Le worker isolé protège aussi l’analyse du projet si un crash natif réapparaît.
- Les imports relatifs internes et les alias configurés avec `baseUrl`/`paths` dans le `tsconfig.json` ou `jsconfig.json` applicable peuvent être résolus vers les fichiers effectivement analysés. Les extensions connues et fichiers `index` sont réutilisés; les paquets externes et chemins dynamiques ne sont pas résolus.
- Les configurations sont lues comme JSONC statique, jamais exécutées. Seuls les `extends` locaux relatifs et confinés à la racine du projet sont suivis (fichiers `.json`/`.jsonc`; un chemin sans extension tente `.json`); chaque chemin est relatif au fichier qui le déclare et les tableaux de parents sont appliqués dans l’ordre. Seuls `baseUrl` et `paths` sont pris en compte pour la résolution; les autres options de compilation ne sont pas reproduites, et les caches sont propres à chaque analyse. Les paquets externes, chemins absolus/hors racine, liens symboliques, références de projets, workspaces et exports conditionnels ne sont pas suivis. Les configurations invalides, les cycles, les parents absents et les formes non prises en charge laissent les alias non résolus sans interrompre les autres relations.
- `CALLS` est limité aux cibles statiquement identifiables par liaison unique ou par une variable locale initialisée avant l’appel avec `new Classe()`, si la classe cible et sa méthode d’instance directe sont uniques. Les méthodes statiques, les instances réassignées/ombrées, le dispatch hérité ou ambigu, `this` et les cibles dynamiques restent non résolus. L’absence d’une arête ne prouve pas l’absence d’une dépendance à l’exécution.
- La résolution d’héritage et d’implémentation est également statique et conservatrice.

La fixture `examples/demo-ts` couvre les imports relatifs, les symboles et relations, un import non résolu, un fichier sensible ignoré et une erreur de syntaxe.

## Tests et qualité

Depuis la racine, avec l’environnement uv installé :

```bash
uv run pytest
uv run ruff check codegraph tests
uv run ruff format --check codegraph tests
```

Les tests exercent le scanner, les grammaires Tree-sitter, l’extraction, les résolutions, les IDs stables, l’export JSON, le rapport, la CLI et les routes/validations de l’API.
