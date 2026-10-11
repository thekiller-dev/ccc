"""Extract symbols, imports, inheritance, and statically visible call sites."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .models import (
    CallSite,
    FileAnalysis,
    GraphNode,
    ImportBinding,
    ImportSpec,
    InheritanceSpec,
    ParsedFile,
    SymbolInfo,
)

_FUNCTION_NODES = {
    "function_declaration",
    "generator_function_declaration",
    "method_definition",
}
_CLASS_NODES = {"class_declaration", "abstract_class_declaration", "class"}


def _text(node: Any | None) -> str:
    if node is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


def _line(node: Any) -> int:
    return node.start_point.row + 1


def _end_line(node: Any) -> int:
    return node.end_point.row + 1


def _source_string(node: Any) -> str:
    value = _text(node)
    if len(value) >= 2 and value[0] in {'"', "'", "`"}:
        return value[1:-1].replace(r"\/", "/")
    return value


def _binding_pattern_names(node: Any | None) -> set[str]:
    if node is None:
        return set()
    if node.type in {"identifier", "shorthand_property_identifier_pattern"}:
        return {_text(node)}
    if node.type == "pair_pattern":
        return _binding_pattern_names(node.child_by_field_name("value"))
    if node.type in {"required_parameter", "optional_parameter"}:
        return _binding_pattern_names(
            node.child_by_field_name("pattern") or node.child_by_field_name("name")
        )
    if node.type in {"assignment_pattern", "default_parameter"}:
        return _binding_pattern_names(
            node.child_by_field_name("left") or node.child_by_field_name("pattern")
        )
    if node.type == "type_annotation":
        return set()
    names: set[str] = set()
    for child in node.named_children:
        names.update(_binding_pattern_names(child))
    return names


def _function_local_bindings(function_node: Any) -> frozenset[str]:
    """Collect likely local bindings to avoid resolving shadowed call names."""

    names: set[str] = set()
    parameters = function_node.child_by_field_name("parameters")
    if parameters is not None:
        for parameter in parameters.named_children:
            names.update(_binding_pattern_names(parameter))

    body = function_node.child_by_field_name("body")
    if body is None:
        return frozenset(names)
    pending = list(body.named_children)
    callable_nodes = {"arrow_function", "function_expression"}
    while pending:
        current = pending.pop()
        if current.type in _FUNCTION_NODES | _CLASS_NODES | callable_nodes:
            name_node = current.child_by_field_name("name")
            if name_node is not None:
                names.add(_text(name_node))
            continue
        if current.type == "variable_declarator":
            names.update(_binding_pattern_names(current.child_by_field_name("name")))
        if current.type == "catch_clause":
            names.update(_binding_pattern_names(current.child_by_field_name("parameter")))
        pending.extend(current.named_children)
    return frozenset(names)


def _qualified_type_name(node: Any | None) -> str:
    if node is None:
        return ""
    if node.type in {"identifier", "type_identifier", "nested_type_identifier"}:
        return _text(node)
    if node.type in {"member_expression", "nested_type_identifier"}:
        named = node.named_children
        if len(named) >= 2:
            return f"{_qualified_type_name(named[0])}.{_qualified_type_name(named[-1])}"
    if node.type in {"generic_type", "type_arguments"} and node.named_children:
        return _qualified_type_name(node.named_children[0])
    if node.type in {"expression", "parenthesized_type"} and node.named_children:
        return _qualified_type_name(node.named_children[0])
    return _text(node).split("<", 1)[0].strip()


def _function_local_instance_types(function_node: Any) -> tuple[tuple[str, str, int], ...]:
    """Infer only direct-body locals initialized with one unambiguous class constructor."""

    body = function_node.child_by_field_name("body")
    parameters = function_node.child_by_field_name("parameters")
    parameter_names = (
        {
            name
            for parameter in parameters.named_children
            for name in _binding_pattern_names(parameter)
        }
        if parameters is not None
        else set()
    )
    declarations: dict[str, list[tuple[str | None, int]]] = {}
    if body is None:
        return ()

    for statement in body.named_children:
        if statement.type not in {"lexical_declaration", "variable_declaration"}:
            continue
        for declarator in statement.named_children:
            if declarator.type != "variable_declarator":
                continue
            name_node = declarator.child_by_field_name("name")
            if name_node is None or name_node.type != "identifier":
                continue
            value_node = declarator.child_by_field_name("value")
            constructor_name = None
            if value_node is not None and value_node.type == "new_expression":
                constructor_name = (
                    _qualified_type_name(value_node.child_by_field_name("constructor")) or None
                )
            declarations.setdefault(_text(name_node), []).append(
                (constructor_name, declarator.end_byte)
            )

    return tuple(
        sorted(
            (name, constructor_name, end_byte)
            for name, candidates in declarations.items()
            if name not in parameter_names and len(candidates) == 1
            for constructor_name, end_byte in candidates
            if constructor_name
        )
    )


def _function_reassigned_names(function_node: Any) -> frozenset[str]:
    """Collect mutations, including nested closures that may change a captured local."""

    body = function_node.child_by_field_name("body")
    if body is None:
        return frozenset()
    names: set[str] = set()
    pending = list(body.named_children)
    while pending:
        current = pending.pop()
        if current.type in {"assignment_expression", "augmented_assignment_expression"}:
            names.update(_binding_pattern_names(current.child_by_field_name("left")))
        elif current.type == "update_expression":
            names.update(
                _binding_pattern_names(
                    current.named_children[0] if current.named_children else None
                )
            )
        pending.extend(current.named_children)
    return frozenset(names)


def _member_call_parts(node: Any | None) -> tuple[str | None, str | None]:
    if node is None or node.type not in {"member_expression", "optional_chain"}:
        return None, None
    object_node = node.child_by_field_name("object")
    property_node = node.child_by_field_name("property")
    if (
        object_node is None
        or object_node.type != "identifier"
        or property_node is None
        or property_node.type not in {"property_identifier", "private_property_identifier"}
    ):
        return None, None
    return _text(object_node), _text(property_node)


def _receiver_instance_type(
    receiver_name: str | None,
    function_stack: tuple[_FunctionFrame, ...],
    call_start_byte: int,
) -> str | None:
    if receiver_name is None:
        return None
    for frame in reversed(function_stack):
        if receiver_name in frame.local_bindings:
            instance_binding = {
                name: (type_name, end_byte) for name, type_name, end_byte in frame.instance_types
            }.get(receiver_name)
            if instance_binding is not None and instance_binding[1] <= call_start_byte:
                return instance_binding[0]
            return None
    return None


def _receiver_is_reassigned(
    receiver_name: str | None, function_stack: tuple[_FunctionFrame, ...]
) -> bool:
    if receiver_name is None:
        return False
    for index in range(len(function_stack) - 1, -1, -1):
        if receiver_name in function_stack[index].local_bindings:
            return any(receiver_name in frame.reassigned_names for frame in function_stack[index:])
    return False


def _callee_name(node: Any | None) -> str:
    if node is None:
        return ""
    if node.type in {"identifier", "property_identifier", "private_property_identifier", "this"}:
        return _text(node)
    if node.type in {"member_expression", "optional_chain"}:
        object_node = node.child_by_field_name("object")
        property_node = node.child_by_field_name("property")
        if object_node is not None and property_node is not None:
            left = _callee_name(object_node)
            right = _callee_name(property_node)
            return f"{left}.{right}" if left and right else ""
    return ""


def _pattern_import_bindings(pattern: Any | None) -> tuple[ImportBinding, ...]:
    if pattern is None:
        return ()
    bindings: list[ImportBinding] = []
    pending = [pattern]
    while pending:
        node = pending.pop()
        if node.type == "shorthand_property_identifier_pattern":
            name = _text(node)
            bindings.append(ImportBinding(imported_name=name, local_name=name))
        elif node.type == "pair_pattern":
            key = node.child_by_field_name("key")
            value = node.child_by_field_name("value")
            if key is not None and value is not None:
                names = _binding_pattern_names(value)
                if len(names) == 1:
                    bindings.append(
                        ImportBinding(imported_name=_text(key), local_name=next(iter(names)))
                    )
                else:
                    pending.extend(reversed(value.named_children))
        else:
            pending.extend(reversed(node.named_children))
    deduplicated = {(item.imported_name, item.local_name): item for item in bindings}
    return tuple(deduplicated[key] for key in sorted(deduplicated))


@dataclass(frozen=True, slots=True)
class _FunctionFrame:
    node: GraphNode
    class_id: str | None
    local_bindings: frozenset[str]
    instance_types: tuple[tuple[str, str, int], ...] = ()
    reassigned_names: frozenset[str] = frozenset()


class _Extractor:
    def __init__(self, parsed_file: ParsedFile) -> None:
        self.parsed_file = parsed_file
        self.path = parsed_file.source_file.path
        source_path = PurePosixPath(self.path)
        module_name = source_path.with_suffix("").as_posix()
        file_name = source_path.name
        self.file_node = GraphNode(
            id=f"file:{self.path}",
            type="file",
            name=file_name,
            path=self.path,
            metadata={"language": parsed_file.language},
        )
        self.module_node = GraphNode(
            id=f"module:{self.path}",
            type="module",
            name=module_name,
            path=self.path,
            metadata={"language": parsed_file.language},
        )
        self.symbols: list[SymbolInfo] = []
        self.imports: list[ImportSpec] = []
        self.calls: list[CallSite] = []
        self.inheritance: list[InheritanceSpec] = []
        self.issues = list(parsed_file.issues)
        self.occurrences: dict[tuple[str, str], int] = {}
        self.export_aliases: list[tuple[str, str]] = []
        self.reassigned_names: set[str] = set()

    def run(self) -> FileAnalysis:
        root = self.parsed_file.tree.root_node
        self._walk(
            root,
            parent_id=self.module_node.id,
            parent_type="module",
            class_id=None,
            function_stack=(),
        )
        return FileAnalysis(
            path=self.path,
            file_node=self.file_node,
            module_node=self.module_node,
            symbols=tuple(self.symbols),
            imports=tuple(self.imports),
            calls=tuple(self.calls),
            inheritance=tuple(self.inheritance),
            issues=tuple(self.issues),
            export_aliases=tuple(self.export_aliases),
            reassigned_names=frozenset(self.reassigned_names),
        )

    def _create_symbol(
        self,
        node: Any,
        node_type: str,
        name: str,
        parent_id: str,
        parent_type: str,
        class_id: str | None,
        exported_names: tuple[str, ...] = (),
        kind: str | None = None,
    ) -> SymbolInfo:
        scope = next(
            (
                symbol.node.metadata.get("qualified_name", "")
                for symbol in reversed(self.symbols)
                if symbol.node.id == parent_id
            ),
            "",
        )
        qualified_name = f"{scope}.{name}" if scope else name
        occurrence_key = (node_type, qualified_name)
        occurrence = self.occurrences.get(occurrence_key, 0) + 1
        self.occurrences[occurrence_key] = occurrence
        unique_name = qualified_name if occurrence == 1 else f"{qualified_name}#{occurrence}"
        metadata: dict[str, Any] = {
            "qualified_name": qualified_name,
            "language": self.parsed_file.language,
            "exported": bool(exported_names),
            "exported_names": list(exported_names),
            "parent_id": parent_id,
        }
        if kind:
            metadata["declaration_kind"] = kind
        if occurrence > 1:
            metadata["occurrence"] = occurrence
        if class_id:
            metadata["class_id"] = class_id
        graph_node = GraphNode(
            id=f"{node_type}:{self.path}::{unique_name}",
            type=node_type,
            name=name,
            path=self.path,
            start_line=_line(node),
            end_line=_end_line(node),
            metadata=metadata,
        )
        symbol = SymbolInfo(
            node=graph_node,
            parent_id=parent_id,
            parent_type=parent_type,
            class_id=class_id,
            exported_names=exported_names,
            is_static=node.type == "method_definition"
            and any(child.type == "static" for child in node.children),
        )
        self.symbols.append(symbol)
        return symbol

    def _walk(
        self,
        node: Any,
        *,
        parent_id: str,
        parent_type: str,
        class_id: str | None,
        function_stack: tuple[_FunctionFrame, ...],
        exported: bool = False,
        default_export: bool = False,
        allow_calls: bool = True,
    ) -> None:
        node_type = node.type
        if node_type in {"assignment_expression", "augmented_assignment_expression"}:
            self.reassigned_names.update(_binding_pattern_names(node.child_by_field_name("left")))
        elif node_type == "update_expression":
            self.reassigned_names.update(
                _binding_pattern_names(node.named_children[0] if node.named_children else None)
            )

        if node_type == "export_statement":
            self._walk_export(
                node,
                parent_id=parent_id,
                parent_type=parent_type,
                class_id=class_id,
                function_stack=function_stack,
            )
            return

        if node_type == "import_statement":
            self._walk_import(node)
            return

        if node_type in {"lexical_declaration", "variable_declaration"}:
            for child in node.named_children:
                self._walk(
                    child,
                    parent_id=parent_id,
                    parent_type=parent_type,
                    class_id=class_id,
                    function_stack=function_stack,
                    exported=exported,
                    allow_calls=allow_calls,
                )
            return

        if node_type in {"arrow_function", "function_expression"} and default_export:
            symbol = self._create_symbol(
                node,
                "function",
                "default",
                parent_id,
                parent_type,
                class_id,
                ("default",),
                kind=node_type,
            )
            frame = _FunctionFrame(
                symbol.node,
                class_id,
                _function_local_bindings(node),
                _function_local_instance_types(node),
                _function_reassigned_names(node),
            )
            for child in node.named_children:
                self._walk(
                    child,
                    parent_id=symbol.node.id,
                    parent_type="function",
                    class_id=class_id,
                    function_stack=(*function_stack, frame),
                    allow_calls=True,
                )
            return

        if node_type in _FUNCTION_NODES:
            name_node = node.child_by_field_name("name")
            name = _text(name_node) or ("default" if default_export else "<anonymous>")
            export_names = ("default",) if default_export else ((name,) if exported else ())
            symbol = self._create_symbol(
                node,
                "function",
                name,
                parent_id,
                parent_type,
                class_id,
                export_names,
                kind=node_type,
            )
            frame = _FunctionFrame(
                symbol.node,
                class_id,
                _function_local_bindings(node),
                _function_local_instance_types(node),
                _function_reassigned_names(node),
            )
            for child in node.named_children:
                self._walk(
                    child,
                    parent_id=symbol.node.id,
                    parent_type="function",
                    class_id=class_id,
                    function_stack=(*function_stack, frame),
                    allow_calls=True,
                )
            return

        if node_type in _CLASS_NODES:
            name_node = node.child_by_field_name("name")
            name = _text(name_node) or ("default" if default_export else "<anonymous>")
            export_names = ("default",) if default_export else ((name,) if exported else ())
            symbol = self._create_symbol(
                node,
                "class",
                name,
                parent_id,
                parent_type,
                class_id,
                export_names,
                kind=node_type,
            )
            self._read_class_heritage(node, symbol.node)
            for child in node.named_children:
                self._walk(
                    child,
                    parent_id=symbol.node.id,
                    parent_type="class",
                    class_id=symbol.node.id,
                    function_stack=function_stack,
                    allow_calls=allow_calls,
                )
            return

        if node_type == "interface_declaration":
            name_node = node.child_by_field_name("name")
            name = _text(name_node) or "<anonymous>"
            export_names = (name,) if exported else ()
            symbol = self._create_symbol(
                node,
                "interface",
                name,
                parent_id,
                parent_type,
                class_id,
                export_names,
                kind=node_type,
            )
            self._read_interface_heritage(node, symbol.node)
            for child in node.named_children:
                self._walk(
                    child,
                    parent_id=symbol.node.id,
                    parent_type="interface",
                    class_id=None,
                    function_stack=function_stack,
                    allow_calls=allow_calls,
                )
            return

        if node_type == "type_alias_declaration":
            name_node = node.child_by_field_name("name")
            name = _text(name_node) or "<anonymous>"
            export_names = (name,) if exported else ()
            symbol = self._create_symbol(
                node,
                "type",
                name,
                parent_id,
                parent_type,
                class_id,
                export_names,
                kind=node_type,
            )
            for child in node.named_children:
                self._walk(
                    child,
                    parent_id=symbol.node.id,
                    parent_type="type",
                    class_id=None,
                    function_stack=function_stack,
                    allow_calls=allow_calls,
                )
            return

        if node_type == "variable_declarator":
            value_node = node.child_by_field_name("value")
            name_node = node.child_by_field_name("name")
            if value_node is not None and value_node.type in _CLASS_NODES:
                name = _text(name_node)
                if name and name_node.type == "identifier":
                    symbol = self._create_symbol(
                        value_node,
                        "class",
                        name,
                        parent_id,
                        parent_type,
                        class_id,
                        (name,) if exported else (),
                        kind=value_node.type,
                    )
                    self._read_class_heritage(value_node, symbol.node)
                    for child in value_node.named_children:
                        self._walk(
                            child,
                            parent_id=symbol.node.id,
                            parent_type="class",
                            class_id=symbol.node.id,
                            function_stack=function_stack,
                            allow_calls=allow_calls,
                        )
                    return
            if value_node is not None and value_node.type in {
                "arrow_function",
                "function_expression",
            }:
                name = _text(name_node)
                if name and name_node.type == "identifier":
                    export_names = (name,) if exported else ()
                    symbol = self._create_symbol(
                        value_node,
                        "function",
                        name,
                        parent_id,
                        parent_type,
                        class_id,
                        export_names,
                        kind=value_node.type,
                    )
                    frame = _FunctionFrame(
                        symbol.node,
                        class_id,
                        _function_local_bindings(value_node),
                        _function_local_instance_types(value_node),
                        _function_reassigned_names(value_node),
                    )
                    for child in value_node.named_children:
                        self._walk(
                            child,
                            parent_id=symbol.node.id,
                            parent_type="function",
                            class_id=class_id,
                            function_stack=(*function_stack, frame),
                            allow_calls=True,
                        )
                    return

        if node_type == "call_expression":
            function_node = node.child_by_field_name("function")
            callee = _callee_name(function_node)
            receiver_name, member_name = _member_call_parts(function_node)
            receiver_type_name = _receiver_instance_type(
                receiver_name, function_stack, node.start_byte
            )
            receiver_reassigned = _receiver_is_reassigned(receiver_name, function_stack)
            if callee == "require":
                self._walk_require(node, parent_id)
            elif allow_calls and callee and function_stack:
                self.calls.append(
                    CallSite(
                        caller_id=function_stack[-1].node.id,
                        callee=callee,
                        line=_line(node),
                        end_line=_end_line(node),
                        class_id=function_stack[-1].class_id,
                        shadowed_names=frozenset(
                            name for frame in function_stack for name in frame.local_bindings
                        ),
                        evidence=f"Tree-sitter call expression: {callee}",
                        receiver_name=receiver_name,
                        member_name=member_name,
                        receiver_type_name=receiver_type_name,
                        receiver_reassigned=receiver_reassigned,
                    )
                )
            elif allow_calls and callee:
                self.calls.append(
                    CallSite(
                        caller_id=self.module_node.id,
                        callee=callee,
                        line=_line(node),
                        end_line=_end_line(node),
                        evidence=f"Tree-sitter call expression: {callee}",
                    )
                )

        if node_type in {"arrow_function", "function_expression"}:
            allow_calls = False

        for child in node.named_children:
            self._walk(
                child,
                parent_id=parent_id,
                parent_type=parent_type,
                class_id=class_id,
                function_stack=function_stack,
                allow_calls=allow_calls,
            )

    def _walk_export(
        self,
        node: Any,
        *,
        parent_id: str,
        parent_type: str,
        class_id: str | None,
        function_stack: tuple[_FunctionFrame, ...],
    ) -> None:
        source_node = node.child_by_field_name("source")
        if source_node is not None:
            clause = next(
                (child for child in node.named_children if child.type == "export_clause"),
                None,
            )
            bindings: list[ImportBinding] = []
            if clause is not None:
                for specifier in clause.named_children:
                    if specifier.type != "export_specifier":
                        continue
                    imported = _text(specifier.child_by_field_name("name"))
                    exported = _text(specifier.child_by_field_name("alias")) or imported
                    if imported:
                        bindings.append(ImportBinding(imported, exported))
            elif any(child.type == "*" for child in node.children):
                bindings.append(ImportBinding("*", "*"))
            self.imports.append(
                ImportSpec(
                    specifier=_source_string(source_node),
                    bindings=tuple(bindings),
                    line=_line(node),
                    end_line=_end_line(node),
                    evidence=f"Tree-sitter re-export statement: {_text(node)}",
                    syntax="reexport",
                )
            )
            return

        declaration = node.child_by_field_name("declaration")
        default_export = any(child.type == "default" for child in node.children)
        if declaration is not None:
            self._walk(
                declaration,
                parent_id=parent_id,
                parent_type=parent_type,
                class_id=class_id,
                function_stack=function_stack,
                exported=True,
                default_export=default_export,
            )
            return

        clause = next(
            (child for child in node.named_children if child.type == "export_clause"),
            None,
        )
        if clause is not None:
            for specifier in clause.named_children:
                if specifier.type != "export_specifier":
                    continue
                local = _text(specifier.child_by_field_name("name"))
                exported_name = _text(specifier.child_by_field_name("alias")) or local
                if local and exported_name:
                    self.export_aliases.append((local, exported_name))

    def _walk_import(self, node: Any) -> None:
        source_node = node.child_by_field_name("source")
        if source_node is None:
            return
        bindings: list[ImportBinding] = []
        clause = next(
            (child for child in node.named_children if child.type == "import_clause"),
            None,
        )
        if clause is not None:
            for child in clause.named_children:
                if child.type == "identifier":
                    bindings.append(ImportBinding("default", _text(child)))
                elif child.type == "namespace_import":
                    local = next(
                        (
                            _text(item)
                            for item in reversed(child.named_children)
                            if item.type == "identifier"
                        ),
                        "",
                    )
                    if local:
                        bindings.append(ImportBinding("*", local))
                elif child.type == "named_imports":
                    for specifier in child.named_children:
                        if specifier.type != "import_specifier":
                            continue
                        imported = _text(specifier.child_by_field_name("name"))
                        local = _text(specifier.child_by_field_name("alias")) or imported
                        if imported and local:
                            bindings.append(ImportBinding(imported, local))
        raw = _text(node)
        self.imports.append(
            ImportSpec(
                specifier=_source_string(source_node),
                bindings=tuple(bindings),
                line=_line(node),
                end_line=_end_line(node),
                evidence=f"Tree-sitter import statement: {raw}",
                syntax="import",
                type_only=raw.lstrip().startswith("import type "),
            )
        )

    def _walk_require(self, node: Any, parent_id: str) -> None:
        arguments = node.child_by_field_name("arguments")
        if arguments is None or not arguments.named_children:
            return
        argument = arguments.named_children[0]
        if argument.type != "string":
            return
        parent = node.parent
        bindings: tuple[ImportBinding, ...] = ()
        if parent is not None and parent.type == "variable_declarator":
            bindings = _pattern_import_bindings(parent.child_by_field_name("name"))
        self.imports.append(
            ImportSpec(
                specifier=_source_string(argument),
                bindings=bindings,
                line=_line(node),
                end_line=_end_line(node),
                evidence=f"Tree-sitter static require expression: {_text(node)}",
                syntax="require",
            )
        )

    def _read_class_heritage(self, class_node: Any, source: GraphNode) -> None:
        for child in class_node.named_children:
            if child.type != "class_heritage":
                continue
            for heritage in child.named_children:
                if heritage.type == "extends_clause":
                    base = heritage.child_by_field_name("value")
                    name = _qualified_type_name(base)
                    if name:
                        self.inheritance.append(
                            InheritanceSpec(
                                source_id=source.id,
                                name=name,
                                relation_type="EXTENDS",
                                line=_line(heritage),
                                end_line=_end_line(heritage),
                                evidence=f"Tree-sitter class extends clause: {_text(heritage)}",
                            )
                        )
                elif heritage.type == "implements_clause":
                    for base in heritage.named_children:
                        name = _qualified_type_name(base)
                        if name:
                            self.inheritance.append(
                                InheritanceSpec(
                                    source_id=source.id,
                                    name=name,
                                    relation_type="IMPLEMENTS",
                                    line=_line(heritage),
                                    end_line=_end_line(heritage),
                                    evidence=f"Tree-sitter implements clause: {_text(heritage)}",
                                )
                            )
                elif heritage.type in {"identifier", "type_identifier", "member_expression"}:
                    name = _qualified_type_name(heritage)
                    if name:
                        self.inheritance.append(
                            InheritanceSpec(
                                source_id=source.id,
                                name=name,
                                relation_type="EXTENDS",
                                line=_line(heritage),
                                end_line=_end_line(heritage),
                                evidence=f"Tree-sitter class heritage: {_text(child)}",
                            )
                        )

    def _read_interface_heritage(self, interface_node: Any, source: GraphNode) -> None:
        for child in interface_node.named_children:
            if child.type != "extends_type_clause":
                continue
            for base in child.named_children:
                name = _qualified_type_name(base)
                if name:
                    self.inheritance.append(
                        InheritanceSpec(
                            source_id=source.id,
                            name=name,
                            relation_type="EXTENDS",
                            line=_line(child),
                            end_line=_end_line(child),
                            evidence=f"Tree-sitter interface extends clause: {_text(child)}",
                        )
                    )


def extract_file(parsed_file: ParsedFile) -> FileAnalysis:
    """Extract graph-relevant syntax nodes; source code is never evaluated."""

    return _Extractor(parsed_file).run()
