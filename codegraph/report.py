"""Graph statistics and Markdown report generation."""

from __future__ import annotations

from collections import Counter
from typing import Any

import networkx as nx

_SYMBOL_TYPES = {"function", "class", "interface", "type"}


def graph_stats(graph: nx.MultiDiGraph) -> dict[str, Any]:
    metadata = graph.graph.get("metadata", {})
    node_counts = Counter(data.get("type", "unknown") for _, data in graph.nodes(data=True))
    relation_counts = Counter(data.get("type", "unknown") for _, _, data in graph.edges(data=True))
    return {
        "schema_version": graph.graph.get("schema_version", "1.0"),
        "project": next(
            (
                data.get("name")
                for _, data in graph.nodes(data=True)
                if data.get("type") == "project"
            ),
            "project",
        ),
        "files": node_counts.get("file", 0),
        "symbols": sum(node_counts.get(node_type, 0) for node_type in _SYMBOL_TYPES),
        "nodes": graph.number_of_nodes(),
        "relations": graph.number_of_edges(),
        "nodes_by_type": dict(sorted(node_counts.items())),
        "relations_by_type": dict(sorted(relation_counts.items())),
        "imports": {
            "total": metadata.get("imports_total", 0),
            "resolved": metadata.get("imports_resolved", 0),
        },
        "calls": {
            "total": metadata.get("calls_total", 0),
            "resolved": metadata.get("calls_resolved", 0),
        },
        "inheritance": {
            "total": metadata.get("inheritance_total", 0),
            "resolved": metadata.get("inheritance_resolved", 0),
        },
        "issues": len(metadata.get("issues", [])),
        "max_file_size_bytes": metadata.get("max_file_size_bytes", 0),
    }


def render_report(graph: nx.MultiDiGraph) -> str:
    metadata = graph.graph.get("metadata", {})
    stats = graph_stats(graph)
    inbound = Counter(
        target
        for _, target, data in graph.edges(data=True)
        if data.get("type") in {"CALLS", "IMPORTS"}
    )
    symbols = [
        (node_id, data)
        for node_id, data in graph.nodes(data=True)
        if data.get("type") in _SYMBOL_TYPES
    ]
    symbols.sort(
        key=lambda item: (
            -inbound[item[0]],
            item[1].get("path", ""),
            item[1].get("start_line") or 0,
            item[1].get("name", ""),
        )
    )
    lines = [
        "# CodeGraph — rapport d’analyse",
        "",
        "## Statistiques",
        "",
        f"- Fichiers découverts / analysés : **{metadata.get('discovered_files', 0)} / "
        f"{stats['files']}**",
        f"- Symboles : **{stats['symbols']}**",
        f"- Nœuds / relations : **{stats['nodes']} / {stats['relations']}**",
        f"- Imports résolus : **{stats['imports']['resolved']} / {stats['imports']['total']}**",
        f"- Appels résolus statiquement : **{stats['calls']['resolved']} / "
        f"{stats['calls']['total']}**",
        f"- Héritages / implémentations résolus : **{stats['inheritance']['resolved']} / "
        f"{stats['inheritance']['total']}**",
        f"- Problèmes : **{stats['issues']}**",
        f"- Limite par fichier : **{stats['max_file_size_bytes']} octets**",
        "",
        "### Nœuds par type",
        "",
    ]
    if stats["nodes_by_type"]:
        lines.extend(
            f"- {node_type}: {count}" for node_type, count in stats["nodes_by_type"].items()
        )
    else:
        lines.append("- Aucun nœud")

    lines.extend(["", "### Relations par type", ""])
    if stats["relations_by_type"]:
        lines.extend(
            f"- {relation_type}: {count}"
            for relation_type, count in stats["relations_by_type"].items()
        )
    else:
        lines.append("- Aucune relation")

    lines.extend(["", "## Symboles principaux", ""])
    if symbols:
        for node_id, node in symbols[:12]:
            location = f"{node.get('path', '?')}:{node.get('start_line') or '?'}"
            lines.append(
                f"- `{node.get('type')}` **{node.get('name')}** — `{location}` "
                f"({inbound[node_id]} relation(s) entrante(s))"
            )
    else:
        lines.append("Aucun symbole extrait.")

    lines.extend(["", "## Problèmes de scan ou d’analyse", ""])
    issues = metadata.get("issues", [])
    if issues:
        for issue in issues:
            location = f"`{issue.get('path', '?')}`"
            if issue.get("line") is not None:
                location += f":{issue['line']}"
            lines.append(
                f"- {location} — **{issue.get('reason', 'issue')}**: {issue.get('message', '')}"
            )
    else:
        lines.append("Aucun problème signalé.")

    unresolved_imports = metadata.get("unresolved_imports", [])
    lines.extend(["", "### Imports non résolus", ""])
    if unresolved_imports:
        lines.extend(
            f"- `{item.get('path')}`:{item.get('line')} — `{item.get('specifier')}`"
            for item in unresolved_imports[:50]
        )
    else:
        lines.append("Aucun.")

    lines.extend(
        [
            "",
            "## Limites et sécurité",
            "",
            "- Le code source n’est jamais exécuté et aucun contenu n’est envoyé à un service "
            "externe.",
            "- Les imports relatifs utilisent des extensions connues et des fichiers `index`; "
            "les alias `paths` de tsconfig, les dépendances externes et les exports CommonJS "
            "complexes restent non résolus.",
            "- Les relations `CALLS`, `IMPORTS`, `EXTENDS` et `IMPLEMENTS` sont des inférences "
            "statiques avec confiance explicite. Les appels dynamiques, les accès calculés, "
            "les surcharges via `this` et les cibles ambiguës ne sont pas reliés.",
            "- Les fichiers trop volumineux, illisibles, non UTF-8, sensibles ou contenant "
            "un marqueur de clé privée sont exclus. Les liens symboliques ne sont pas suivis.",
            "- Les erreurs Tree-sitter peuvent laisser un arbre récupéré partiel ; les "
            "diagnostics sont exposés dans ce rapport et les réponses API.",
            "",
        ]
    )
    return "\n".join(lines)
