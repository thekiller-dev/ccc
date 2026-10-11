"""Conservative resolution of relative/configured imports, calls, and type heritage."""

from __future__ import annotations

import posixpath
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .models import CallSite, FileAnalysis, GraphNode, GraphRelation, Provenance
from .tsconfig import ProjectPathConfig, ProjectPathConfigResolver

_SOURCE_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs")
_EXPLICIT_EXTENSION_ALTERNATES = {
    ".js": (".js", ".ts", ".tsx"),
    ".jsx": (".jsx", ".tsx"),
    ".ts": (".ts",),
    ".tsx": (".tsx",),
    ".mts": (".mts",),
    ".cts": (".cts",),
    ".mjs": (".mjs", ".mts"),
    ".cjs": (".cjs", ".cts"),
}


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    relations: tuple[GraphRelation, ...]
    imports_total: int
    imports_resolved: int
    calls_total: int
    calls_resolved: int
    inheritance_total: int
    inheritance_resolved: int
    unresolved_imports: tuple[dict[str, object], ...]
    unresolved_calls: tuple[dict[str, object], ...]


def _candidate_paths_from_base(base: str) -> tuple[str, ...]:
    """Apply the existing extension/index policy to a project-relative base."""

    if base == ".." or base.startswith("../") or base.startswith("/"):
        return ()

    suffix = PurePosixPath(base).suffix.lower()
    if suffix:
        extensions = _EXPLICIT_EXTENSION_ALTERNATES.get(suffix)
        if extensions is None:
            return ()
        stem = base[: -len(suffix)]
        candidates = [stem + extension for extension in extensions]
    else:
        extensions = _SOURCE_EXTENSIONS
        stem = "" if base == "." else base.rstrip("/")
        candidates = [stem + extension for extension in extensions] if stem else []
        index_base = f"{stem}/" if stem else ""
        candidates.extend(f"{index_base}index{extension}" for extension in extensions)
    return tuple(dict.fromkeys(candidates))


def _candidate_paths(importer_path: str, specifier: str) -> tuple[str, ...]:
    if not specifier.startswith(".") or "?" in specifier or "#" in specifier:
        return ()
    base = posixpath.normpath(posixpath.join(posixpath.dirname(importer_path), specifier))
    return _candidate_paths_from_base(base)


def _resolve_file(
    importer_path: str,
    specifier: str,
    file_index: dict[str, FileAnalysis],
    path_config: ProjectPathConfig | None = None,
) -> FileAnalysis | None:
    if specifier.startswith("."):
        candidates = _candidate_paths(importer_path, specifier)
    elif path_config is not None:
        candidates = tuple(
            candidate
            for base in path_config.candidate_bases(specifier)
            for candidate in _candidate_paths_from_base(base)
        )
    else:
        # Bare package specifiers are not treated as project-relative imports
        # unless an applicable local tsconfig/jsconfig explicitly maps them.
        candidates = ()

    for candidate in dict.fromkeys(candidates):
        if candidate in file_index:
            return file_index[candidate]
    return None


def _provenance(
    path: str,
    line: int,
    end_line: int,
    evidence: str,
    method: str,
) -> Provenance:
    return Provenance(path, line, end_line, evidence, method)


def _unique_export(
    analysis: FileAnalysis,
    exported_name: str,
    exports_by_path: dict[str, dict[str, tuple[GraphNode, ...]]] | None = None,
) -> GraphNode | None:
    exports = (
        exports_by_path.get(analysis.path, {}) if exports_by_path is not None else analysis.exports
    )
    matches = {node.id: node for node in exports.get(exported_name, ())}
    return next(iter(matches.values())) if len(matches) == 1 else None


def _build_export_index(
    analyses: tuple[FileAnalysis, ...] | list[FileAnalysis],
    resolved_import_targets: dict[tuple[str, int], FileAnalysis | None],
) -> dict[str, dict[str, tuple[GraphNode, ...]]]:
    """Propagate named and star re-exports to a fixed point across modules."""

    mutable_exports: dict[str, dict[str, dict[str, GraphNode]]] = {}
    for analysis in analyses:
        mutable_exports[analysis.path] = {
            name: {node.id: node for node in nodes} for name, nodes in analysis.exports.items()
        }

    changed = True
    while changed:
        changed = False
        for analysis in analyses:
            source_exports = mutable_exports[analysis.path]
            for index, spec in enumerate(analysis.imports):
                target_analysis = resolved_import_targets.get((analysis.path, index))
                if target_analysis is None:
                    continue
                target_exports = mutable_exports.get(target_analysis.path, {})
                if spec.syntax == "reexport":
                    for binding in spec.bindings:
                        if binding.imported_name == "*":
                            destinations = (
                                (name, nodes)
                                for name, nodes in target_exports.items()
                                if name != "default"
                            )
                        else:
                            destinations = (
                                (binding.local_name, target_exports.get(binding.imported_name, {})),
                            )
                        for exported_name, nodes in destinations:
                            if not exported_name:
                                continue
                            current = source_exports.setdefault(exported_name, {})
                            for node_id, node in nodes.items():
                                if node_id not in current:
                                    current[node_id] = node
                                    changed = True
                    continue

                for local_name, exported_name in analysis.export_aliases:
                    for binding in spec.bindings:
                        if binding.local_name != local_name or binding.imported_name == "*":
                            continue
                        nodes = target_exports.get(binding.imported_name, {})
                        current = source_exports.setdefault(exported_name, {})
                        for node_id, node in nodes.items():
                            if node_id not in current:
                                current[node_id] = node
                                changed = True

    return {
        path: {
            name: tuple(nodes[node_id] for node_id in sorted(nodes))
            for name, nodes in exports.items()
        }
        for path, exports in mutable_exports.items()
    }


def _local_symbols(analysis: FileAnalysis, name: str) -> list[GraphNode]:
    return [
        symbol.node
        for symbol in analysis.symbols
        if symbol.parent_type == "module"
        and symbol.node.name == name
        and symbol.node.type in {"function", "class", "interface", "type"}
    ]


def _resolve_binding_target(
    analysis: FileAnalysis,
    name: str,
    bindings: dict[tuple[str, str], GraphNode | None],
    module_by_id: dict[str, FileAnalysis],
    exports_by_path: dict[str, dict[str, tuple[GraphNode, ...]]] | None = None,
) -> GraphNode | None:
    if "." in name:
        prefix, member = name.split(".", 1)
        binding = bindings.get((analysis.path, prefix))
        if binding is not None and binding.type == "module":
            target_analysis = module_by_id.get(binding.id)
            return (
                _unique_export(target_analysis, member, exports_by_path)
                if target_analysis
                else None
            )
        return None

    key = (analysis.path, name)
    if key in bindings:
        return bindings[key]
    candidates = {node.id: node for node in _local_symbols(analysis, name)}
    return next(iter(candidates.values())) if len(candidates) == 1 else None


def _resolve_call_target(
    analysis: FileAnalysis,
    callee: str,
    shadowed_names: frozenset[str],
    bindings: dict[tuple[str, str], GraphNode | None],
    type_only_bindings: set[tuple[str, str]],
    module_by_id: dict[str, FileAnalysis],
    reassigned_names: frozenset[str],
    exports_by_path: dict[str, dict[str, tuple[GraphNode, ...]]] | None = None,
) -> GraphNode | None:
    if callee.startswith("this.") or not callee:
        # `this.method()` can dispatch to an override at runtime; don't turn it
        # into a confirmed edge based only on the enclosing class body.
        return None
    first_name = callee.split(".", 1)[0]
    if first_name in shadowed_names or first_name in reassigned_names:
        return None
    if (analysis.path, first_name) in type_only_bindings:
        return None

    target = _resolve_binding_target(analysis, callee, bindings, module_by_id, exports_by_path)
    if target is None or target.type not in {"function", "class"}:
        return None
    return target


def _resolve_heritage_target(
    analysis: FileAnalysis,
    source_id: str,
    name: str,
    relation_type: str,
    bindings: dict[tuple[str, str], GraphNode | None],
    module_by_id: dict[str, FileAnalysis],
    exports_by_path: dict[str, dict[str, tuple[GraphNode, ...]]] | None = None,
) -> GraphNode | None:
    source = next((symbol.node for symbol in analysis.symbols if symbol.node.id == source_id), None)
    target = _resolve_binding_target(analysis, name, bindings, module_by_id, exports_by_path)
    if source is None or target is None:
        return None
    if relation_type == "IMPLEMENTS":
        return target if source.type == "class" and target.type == "interface" else None
    if source.type == "class" and target.type == "class":
        return target
    if source.type == "interface" and target.type == "interface":
        return target
    return None


def _resolve_instance_method_target(
    analysis: FileAnalysis,
    call: CallSite,
    bindings: dict[tuple[str, str], GraphNode | None],
    type_only_bindings: set[tuple[str, str]],
    module_by_id: dict[str, FileAnalysis],
    file_index: dict[str, FileAnalysis],
    exports_by_path: dict[str, dict[str, tuple[GraphNode, ...]]],
) -> GraphNode | None:
    receiver_name = call.receiver_name
    member_name = call.member_name
    receiver_type_name = call.receiver_type_name
    if (
        not receiver_name
        or not member_name
        or not receiver_type_name
        or call.receiver_reassigned
        or receiver_name not in call.shadowed_names
        or receiver_type_name.split(".", 1)[0] in call.shadowed_names
        or (analysis.path, receiver_type_name.split(".", 1)[0]) in type_only_bindings
    ):
        return None

    class_node = _resolve_binding_target(
        analysis, receiver_type_name, bindings, module_by_id, exports_by_path
    )
    if class_node is None or class_node.type != "class":
        return None
    class_analysis = file_index.get(class_node.path)
    if class_analysis is None:
        return None
    matches = {
        symbol.node.id: symbol.node
        for symbol in class_analysis.symbols
        if symbol.parent_type == "class"
        and symbol.class_id == class_node.id
        and symbol.node.type == "function"
        and symbol.node.name == member_name
        and not symbol.is_static
    }
    return next(iter(matches.values())) if len(matches) == 1 else None


def resolve_relationships(
    analyses: tuple[FileAnalysis, ...] | list[FileAnalysis],
    project_root: str | Path | None = None,
) -> ResolutionResult:
    file_index = {analysis.path: analysis for analysis in analyses}
    module_by_id = {analysis.module_node.id: analysis for analysis in analyses}
    path_config_resolver = (
        ProjectPathConfigResolver(project_root) if project_root is not None else None
    )
    resolved_import_targets: dict[tuple[str, int], FileAnalysis | None] = {}
    for importer in analyses:
        path_config = (
            path_config_resolver.for_file(importer.path)
            if path_config_resolver is not None
            else None
        )
        for index, spec in enumerate(importer.imports):
            resolved_import_targets[(importer.path, index)] = _resolve_file(
                importer.path, spec.specifier, file_index, path_config
            )

    exports_by_path = _build_export_index(analyses, resolved_import_targets)
    relations: list[GraphRelation] = []
    binding_candidates: dict[tuple[str, str], list[GraphNode]] = defaultdict(list)
    seen_bindings: set[tuple[str, str]] = set()
    type_only_bindings: set[tuple[str, str]] = set()
    unresolved_imports: list[dict[str, object]] = []
    unresolved_calls: list[dict[str, object]] = []

    imports_total = sum(len(analysis.imports) for analysis in analyses)
    imports_resolved = 0
    for importer in analyses:
        for index, spec in enumerate(importer.imports):
            relative_import = spec.specifier.startswith(".")
            path_resolution_method = (
                "relative-path-resolution" if relative_import else "tsconfig-path-resolution"
            )
            symbol_resolution_method = (
                "tree-sitter+export-binding-resolution"
                if relative_import
                else "tree-sitter+tsconfig-path-resolution+export-binding-resolution"
            )
            target_analysis = resolved_import_targets[(importer.path, index)]
            if target_analysis is None:
                unresolved_imports.append(
                    {"path": importer.path, "specifier": spec.specifier, "line": spec.line}
                )
                if spec.syntax != "reexport":
                    for binding in spec.bindings:
                        key = (importer.path, binding.local_name)
                        seen_bindings.add(key)
                        if spec.type_only:
                            type_only_bindings.add(key)
                continue

            imports_resolved += 1
            relations.append(
                GraphRelation.create(
                    importer.module_node.id,
                    target_analysis.module_node.id,
                    "IMPORTS",
                    _provenance(
                        importer.path,
                        spec.line,
                        spec.end_line,
                        spec.evidence,
                        f"tree-sitter+{path_resolution_method}",
                    ),
                    confidence=0.98,
                    inferred=True,
                )
            )
            for binding in spec.bindings:
                key = (importer.path, binding.local_name)
                if spec.syntax != "reexport":
                    seen_bindings.add(key)
                    if spec.type_only:
                        type_only_bindings.add(key)
                if binding.imported_name == "*":
                    if spec.syntax != "reexport":
                        binding_candidates[key].append(target_analysis.module_node)
                    continue
                target_symbol = _unique_export(
                    target_analysis, binding.imported_name, exports_by_path
                )
                if target_symbol is not None:
                    relations.append(
                        GraphRelation.create(
                            importer.module_node.id,
                            target_symbol.id,
                            "IMPORTS",
                            _provenance(
                                importer.path,
                                spec.line,
                                spec.end_line,
                                f"{spec.evidence}; imported symbol: {binding.imported_name}",
                                symbol_resolution_method,
                            ),
                            confidence=0.92,
                            inferred=True,
                        )
                    )
                    if spec.syntax != "reexport":
                        binding_candidates[key].append(target_symbol)

    bindings: dict[tuple[str, str], GraphNode | None] = {}
    for key in seen_bindings:
        candidates = {node.id: node for node in binding_candidates.get(key, [])}
        bindings[key] = next(iter(candidates.values())) if len(candidates) == 1 else None

    calls_total = sum(len(analysis.calls) for analysis in analyses)
    calls_resolved = 0
    for analysis in analyses:
        for call in analysis.calls:
            target = _resolve_instance_method_target(
                analysis,
                call,
                bindings,
                type_only_bindings,
                module_by_id,
                file_index,
                exports_by_path,
            )
            resolution_method = "tree-sitter+local-instance-type+unique-class-method"
            if target is None:
                target = _resolve_call_target(
                    analysis,
                    call.callee,
                    call.shadowed_names,
                    bindings,
                    type_only_bindings,
                    module_by_id,
                    analysis.reassigned_names,
                    exports_by_path,
                )
                resolution_method = "tree-sitter+unique-static-binding"
            if target is None:
                unresolved_calls.append(
                    {"path": analysis.path, "callee": call.callee, "line": call.line}
                )
                continue
            calls_resolved += 1
            relations.append(
                GraphRelation.create(
                    call.caller_id,
                    target.id,
                    "CALLS",
                    _provenance(
                        analysis.path,
                        call.line,
                        call.end_line,
                        call.evidence,
                        resolution_method,
                    ),
                    confidence=0.9,
                    inferred=True,
                )
            )

    inheritance_total = sum(len(analysis.inheritance) for analysis in analyses)
    inheritance_resolved = 0
    for analysis in analyses:
        for heritage in analysis.inheritance:
            target = _resolve_heritage_target(
                analysis,
                heritage.source_id,
                heritage.name,
                heritage.relation_type,
                bindings,
                module_by_id,
                exports_by_path,
            )
            if target is None:
                continue
            inheritance_resolved += 1
            relations.append(
                GraphRelation.create(
                    heritage.source_id,
                    target.id,
                    heritage.relation_type,
                    _provenance(
                        analysis.path,
                        heritage.line,
                        heritage.end_line,
                        heritage.evidence,
                        "tree-sitter+unique-static-binding",
                    ),
                    confidence=0.94,
                    inferred=True,
                )
            )

    unresolved_imports.sort(key=lambda item: (str(item["path"]), int(item["line"])))
    unresolved_calls.sort(key=lambda item: (str(item["path"]), int(item["line"])))
    relations.sort(key=lambda item: (item.source, item.target, item.type, item.id))
    return ResolutionResult(
        relations=tuple(relations),
        imports_total=imports_total,
        imports_resolved=imports_resolved,
        calls_total=calls_total,
        calls_resolved=calls_resolved,
        inheritance_total=inheritance_total,
        inheritance_resolved=inheritance_resolved,
        unresolved_imports=tuple(unresolved_imports),
        unresolved_calls=tuple(unresolved_calls),
    )
