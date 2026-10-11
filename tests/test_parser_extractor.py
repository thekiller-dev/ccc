from __future__ import annotations

from codegraph.extractor import extract_file
from codegraph.models import ScannedFile
from codegraph.parser import parse_file


def test_parser_selects_tree_sitter_grammars_for_all_extensions() -> None:
    samples = {
        "x.js": ("javascript", b"function f() { return 1; }"),
        "x.jsx": ("javascript", b"const C = () => <div />;"),
        "x.mjs": ("javascript", b"export const f = () => 1;"),
        "x.cjs": ("javascript", b"module.exports = function f() {};"),
        "x.ts": ("typescript", b"export interface I { value: string }"),
        "x.mts": ("typescript", b"export type T = string;"),
        "x.cts": ("typescript", b"export class C {}"),
        "x.tsx": ("tsx", b"const C = () => <main />;"),
    }
    for path, (language, source) in samples.items():
        parsed = parse_file(ScannedFile(path, source))
        assert parsed.language == language
        assert not parsed.issues


def test_extractor_finds_types_symbols_imports_calls_and_heritage() -> None:
    source = b"""import DefaultThing, { greet as say } from "./greet";
import * as widgets from "./widgets";
export interface Greeting extends BaseGreeting { text: string }
export type Message = string;
export class Greeter extends Parent implements Greeting {
  greet(name: string) { return say(name); }
}
export const run = (name: string) => say(name);
"""
    analysis = extract_file(parse_file(ScannedFile("src/main.ts", source)))

    symbols = {(item.node.type, item.node.name) for item in analysis.symbols}
    assert {("interface", "Greeting"), ("type", "Message"), ("class", "Greeter")} <= symbols
    assert ("function", "greet") in symbols
    assert ("function", "run") in symbols
    assert analysis.imports[0].bindings[0].imported_name == "default"
    assert analysis.imports[0].bindings[0].local_name == "DefaultThing"
    assert analysis.imports[0].bindings[1].imported_name == "greet"
    assert analysis.imports[0].bindings[1].local_name == "say"
    assert analysis.imports[1].bindings[0].imported_name == "*"
    assert analysis.imports[1].bindings[0].local_name == "widgets"
    assert any(call.callee == "say" for call in analysis.calls)
    assert {item.relation_type for item in analysis.inheritance} == {"EXTENDS", "IMPLEMENTS"}
    assert analysis.exports["Greeting"]
    assert analysis.exports["Message"]


def test_exported_arrow_functions_are_exported_and_local_shadows_are_recorded() -> None:
    parsed = parse_file(
        ScannedFile(
            "file.ts",
            b"export const entry = (target: () => void) => target();\n",
        )
    )
    analysis = extract_file(parsed)
    arrow = next(item for item in analysis.symbols if item.node.name == "entry")

    assert arrow.exported_names == ("entry",)
    assert analysis.calls[0].callee == "target"
    assert "target" in analysis.calls[0].shadowed_names


def test_tree_sitter_reports_errors_but_retains_partial_analysis() -> None:
    parsed = parse_file(ScannedFile("broken.ts", b"export function broken( { return 1; }"))
    analysis = extract_file(parsed)

    assert parsed.issues
    assert parsed.issues[0].reason == "syntax_error"
    assert analysis.path == "broken.ts"
    assert analysis.issues


def test_parsing_never_executes_project_code(tmp_path) -> None:
    sentinel = tmp_path / "executed.txt"
    source = f"require('fs').writeFileSync({str(sentinel)!r}, 'no');\nexport function f() {{}}"

    analysis = extract_file(parse_file(ScannedFile("side-effect.ts", source.encode())))

    assert any(item.node.name == "f" for item in analysis.symbols)
    assert not sentinel.exists()
