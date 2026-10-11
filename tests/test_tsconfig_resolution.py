from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import pytest

from codegraph.engine import analyze_project
from codegraph.exporter import graph_to_dict


def _write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _has_relation(graph: nx.MultiDiGraph, source: str, target: str, relation_type: str) -> bool:
    return any(
        data.get("type") == relation_type
        for _, actual_target, data in graph.edges(source, data=True)
        if actual_target == target
    )


def _targets(graph: nx.MultiDiGraph, source: str, relation_type: str) -> set[str]:
    return {
        target
        for _, target, data in graph.out_edges(source, data=True)
        if data.get("type") == relation_type
    }


def _module_import_targets(graph: nx.MultiDiGraph, source: str) -> set[str]:
    return {
        target
        for _, target, data in graph.out_edges(source, data=True)
        if data.get("type") == "IMPORTS" and target.startswith("module:")
    }


def _write_config(root: Path, name: str, compiler_options: str) -> None:
    _write(
        root,
        name,
        '{\n  "compilerOptions": ' + compiler_options + "\n}\n",
    )


def test_wildcard_alias_creates_import_and_call_without_changing_schema(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "tsconfig.json",
        '{"baseUrl": ".", "paths": {"@/*": ["src/*"]}}',
    )
    _write(
        tmp_path,
        "src/main.ts",
        'import { Button } from "@/components/Button";\n'
        "export function render() { return Button(); }\n",
    )
    _write(
        tmp_path,
        "src/components/Button.ts",
        "export function Button() { return 1; }\n",
    )

    graph = analyze_project(tmp_path)
    document = graph_to_dict(graph)
    relation_keys = {
        "id",
        "source",
        "target",
        "type",
        "provenance",
        "confidence",
        "certainty",
        "origin",
        "inferred",
    }

    assert isinstance(graph, nx.MultiDiGraph)
    assert _has_relation(graph, "module:src/main.ts", "module:src/components/Button.ts", "IMPORTS")
    assert _has_relation(
        graph,
        "function:src/main.ts::render",
        "function:src/components/Button.ts::Button",
        "CALLS",
    )
    assert graph.graph["metadata"]["imports_resolved"] == 1
    assert graph.graph["metadata"]["calls_resolved"] == 1
    assert document["schema_version"] == "1.0"
    assert all(relation_keys == set(relation) for relation in document["relations"])
    alias_import = next(
        relation
        for relation in document["relations"]
        if relation["type"] == "IMPORTS" and relation["target"] == "module:src/components/Button.ts"
    )
    assert alias_import["provenance"]["method"] == "tree-sitter+tsconfig-path-resolution"


def test_exact_alias_takes_precedence_over_matching_wildcard(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "tsconfig.json",
        '{"baseUrl": ".", "paths": {"@/Button": ["src/exact.ts"], "@/*": ["src/wildcard/*"]}}',
    )
    _write(
        tmp_path,
        "src/main.ts",
        'import { Button } from "@/Button";\nexport function run() { return Button(); }\n',
    )
    _write(tmp_path, "src/exact.ts", "export function Button() { return 1; }\n")
    _write(tmp_path, "src/wildcard/Button.ts", "export function Button() { return 2; }\n")

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:src/main.ts") == {"module:src/exact.ts"}
    assert _targets(graph, "function:src/main.ts::run", "CALLS") == {
        "function:src/exact.ts::Button"
    }


def test_paths_target_arrays_use_declared_order_and_fall_back(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "tsconfig.json",
        '{"baseUrl": ".", "paths": {'
        '"@/ordered": ["src/first.ts", "src/second.ts"], '
        '"@/fallback": ["src/missing.ts", "src/fallback.ts"]'
        "}}",
    )
    _write(
        tmp_path,
        "src/main.ts",
        'import { first } from "@/ordered";\n'
        'import { fallback } from "@/fallback";\n'
        "export function run() { return first() + fallback(); }\n",
    )
    _write(tmp_path, "src/first.ts", "export function first() { return 1; }\n")
    _write(tmp_path, "src/second.ts", "export function first() { return 2; }\n")
    _write(tmp_path, "src/fallback.ts", "export function fallback() { return 3; }\n")

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:src/main.ts") == {
        "module:src/first.ts",
        "module:src/fallback.ts",
    }
    assert _targets(graph, "function:src/main.ts::run", "CALLS") == {
        "function:src/first.ts::first",
        "function:src/fallback.ts::fallback",
    }
    assert graph.graph["metadata"]["imports_resolved"] == 2


def test_base_url_resolves_bare_local_imports_without_guessing_packages(tmp_path: Path) -> None:
    _write_config(tmp_path, "tsconfig.json", '{"baseUrl": "src"}')
    _write(
        tmp_path,
        "src/main.ts",
        'import { local } from "services/local";\n'
        'import External from "uninstalled-package";\n'
        "export function run() { return local() + External(); }\n",
    )
    _write(tmp_path, "src/services/local.ts", "export function local() { return 1; }\n")
    _write(
        tmp_path,
        "node_modules/uninstalled-package/index.ts",
        "export default function External() { return 2; }\n",
    )

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:src/main.ts") == {"module:src/services/local.ts"}
    assert _targets(graph, "function:src/main.ts::run", "CALLS") == {
        "function:src/services/local.ts::local"
    }
    assert graph.graph["metadata"]["unresolved_imports"] == [
        {"path": "src/main.ts", "specifier": "uninstalled-package", "line": 2}
    ]
    assert graph.graph["metadata"]["calls_resolved"] == 1


def test_alias_targets_reuse_index_and_extension_substitution(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "tsconfig.json",
        '{"baseUrl": ".", "paths": {"@/*": ["src/*"]}}',
    )
    _write(
        tmp_path,
        "src/main.ts",
        'import { fromIndex } from "@/folder";\n'
        'import { fromMappedJs } from "@/mapped.js";\n'
        "export function run() { return fromIndex() + fromMappedJs(); }\n",
    )
    _write(tmp_path, "src/folder/index.ts", "export function fromIndex() { return 1; }\n")
    _write(tmp_path, "src/mapped.ts", "export function fromMappedJs() { return 2; }\n")

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:src/main.ts") == {
        "module:src/folder/index.ts",
        "module:src/mapped.ts",
    }
    assert _targets(graph, "function:src/main.ts::run", "CALLS") == {
        "function:src/folder/index.ts::fromIndex",
        "function:src/mapped.ts::fromMappedJs",
    }


def test_jsconfig_paths_resolve_javascript_imports(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "jsconfig.json",
        '{"baseUrl": ".", "paths": {"@/*": ["src/*"]}}',
    )
    _write(
        tmp_path,
        "src/main.js",
        'import { helper } from "@/lib/helper";\nexport function run() { return helper(); }\n',
    )
    _write(tmp_path, "src/lib/helper.js", "export function helper() { return 1; }\n")

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:src/main.js") == {"module:src/lib/helper.js"}
    assert _targets(graph, "function:src/main.js::run", "CALLS") == {
        "function:src/lib/helper.js::helper"
    }


def test_relative_imports_keep_existing_resolution_with_paths_config(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "tsconfig.json",
        '{"baseUrl": ".", "paths": {"@/*": ["src/*"]}}',
    )
    _write(
        tmp_path,
        "src/main.ts",
        'import { aliasTarget } from "@/aliasTarget";\n'
        'import { relativeTarget } from "./folder";\n'
        "export function run() { return aliasTarget() + relativeTarget(); }\n",
    )
    _write(tmp_path, "src/aliasTarget.ts", "export function aliasTarget() { return 1; }\n")
    _write(tmp_path, "src/folder/index.ts", "export function relativeTarget() { return 2; }\n")

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:src/main.ts") == {
        "module:src/aliasTarget.ts",
        "module:src/folder/index.ts",
    }
    assert _targets(graph, "function:src/main.ts::run", "CALLS") == {
        "function:src/aliasTarget.ts::aliasTarget",
        "function:src/folder/index.ts::relativeTarget",
    }
    relative_import = next(
        data
        for _, target, data in graph.out_edges("module:src/main.ts", data=True)
        if target == "module:src/folder/index.ts" and data["type"] == "IMPORTS"
    )
    assert relative_import["provenance"]["method"] == "tree-sitter+relative-path-resolution"


@pytest.mark.parametrize(
    "config_text",
    [
        None,
        '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}',
        '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"], "@/*": ["other/*"]}}}',
        '{"extends": "@scope/tsconfig/base", "compilerOptions": {"paths": {"@/*": ["src/*"]}}}',
        '{"references": [{"path": "./other"}], "compilerOptions": {"paths": {"@/*": ["src/*"]}}}',
    ],
    ids=[
        "missing",
        "invalid-jsonc",
        "duplicate-keys",
        "package-extends-unsupported",
        "references-unsupported",
    ],
)
def test_absent_invalid_or_unsupported_config_preserves_other_analysis(
    tmp_path: Path, config_text: str | None
) -> None:
    if config_text is not None:
        _write(tmp_path, "tsconfig.json", config_text)
    _write(
        tmp_path,
        "src/main.ts",
        'import { relative } from "./relative";\n'
        'import { alias } from "@/alias";\n'
        "export function run() { return relative() + alias(); }\n",
    )
    _write(tmp_path, "src/relative.ts", "export function relative() { return 1; }\n")

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:src/main.ts") == {"module:src/relative.ts"}
    assert _targets(graph, "function:src/main.ts::run", "CALLS") == {
        "function:src/relative.ts::relative"
    }
    assert graph.graph["metadata"]["unresolved_imports"] == [
        {"path": "src/main.ts", "specifier": "@/alias", "line": 2}
    ]
    assert graph.graph["metadata"]["calls_resolved"] == 1


def test_nonexistent_alias_target_stays_unresolved(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "tsconfig.json",
        '{"baseUrl": ".", "paths": {"@/*": ["src/*"]}}',
    )
    _write(
        tmp_path,
        "src/main.ts",
        'import { missing } from "@/missing";\nexport function run() { return missing(); }\n',
    )

    graph = analyze_project(tmp_path)

    assert not _module_import_targets(graph, "module:src/main.ts")
    assert not _targets(graph, "function:src/main.ts::run", "CALLS")
    assert graph.graph["metadata"]["imports_resolved"] == 0
    assert graph.graph["metadata"]["calls_resolved"] == 0
    assert graph.graph["metadata"]["unresolved_imports"] == [
        {"path": "src/main.ts", "specifier": "@/missing", "line": 1}
    ]


def test_equal_priority_overlapping_wildcards_fail_closed(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "tsconfig.json",
        '{"baseUrl": ".", "paths": {"@/*x": ["src/with-suffix/*"], "@/*": ["src/general/*"]}}',
    )
    _write(
        tmp_path,
        "src/main.ts",
        'import { target } from "@/featurex";\nexport function run() { return target(); }\n',
    )
    _write(tmp_path, "src/with-suffix/feature.ts", "export function target() { return 1; }\n")
    _write(tmp_path, "src/general/featurex.ts", "export function target() { return 2; }\n")

    graph = analyze_project(tmp_path)

    assert not _module_import_targets(graph, "module:src/main.ts")
    assert not _targets(graph, "function:src/main.ts::run", "CALLS")
    assert graph.graph["metadata"]["unresolved_imports"] == [
        {"path": "src/main.ts", "specifier": "@/featurex", "line": 1}
    ]
    assert graph.graph["metadata"]["calls_resolved"] == 0


def test_nested_config_is_selected_and_aliases_stay_inside_project_root(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "tsconfig.json",
        '{"baseUrl": ".", "paths": {"@/*": ["src/*"]}}',
    )
    _write_config(
        tmp_path,
        "packages/app/tsconfig.json",
        '{"baseUrl": ".", "paths": {"@/*": ["local/*"]}}',
    )
    _write(
        tmp_path,
        "packages/app/main.ts",
        'import { target } from "@/target";\nexport function run() { return target(); }\n',
    )
    _write(tmp_path, "packages/app/local/target.ts", "export function target() { return 1; }\n")
    _write(tmp_path, "src/target.ts", "export function target() { return 2; }\n")

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:packages/app/main.ts") == {
        "module:packages/app/local/target.ts"
    }
    assert _targets(graph, "function:packages/app/main.ts::run", "CALLS") == {
        "function:packages/app/local/target.ts::target"
    }


def test_alias_targets_cannot_escape_project_root(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    outside_root = tmp_path / "outside"
    _write_config(
        project_root,
        "tsconfig.json",
        '{"baseUrl": ".", "paths": {"@/*": ["../outside/*"]}}',
    )
    _write(
        project_root,
        "src/main.ts",
        'import { outside } from "@/target";\nexport function run() { return outside(); }\n',
    )
    _write(outside_root, "target.ts", "export function outside() { return 1; }\n")

    graph = analyze_project(project_root)

    assert not _module_import_targets(graph, "module:src/main.ts")
    assert not _targets(graph, "function:src/main.ts::run", "CALLS")
    assert graph.graph["metadata"]["unresolved_imports"] == [
        {"path": "src/main.ts", "specifier": "@/target", "line": 1}
    ]


def test_alias_mapping_cannot_bypass_scanner_exclusions(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "tsconfig.json",
        '{"baseUrl": ".", "paths": {"external": ["node_modules/external/index.ts"]}}',
    )
    _write(
        tmp_path,
        "src/main.ts",
        'import { external } from "external";\nexport function run() { return external(); }\n',
    )
    _write(
        tmp_path,
        "node_modules/external/index.ts",
        "export function external() { return 1; }\n",
    )

    graph = analyze_project(tmp_path)

    assert not _module_import_targets(graph, "module:src/main.ts")
    assert not _targets(graph, "function:src/main.ts::run", "CALLS")
    assert graph.graph["metadata"]["unresolved_imports"] == [
        {"path": "src/main.ts", "specifier": "external", "line": 1}
    ]


def test_jsonc_comments_and_trailing_commas_are_accepted(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tsconfig.json",
        """{
          // This is data, not executable configuration.
          "compilerOptions": {
            "baseUrl": ".",
            "paths": { "@/*": ["src/*",], },
          },
        }
        """,
    )
    _write(tmp_path, "src/main.ts", 'import { helper } from "@/helper";\n')
    _write(tmp_path, "src/helper.ts", "export function helper() { return 1; }\n")

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:src/main.ts") == {"module:src/helper.ts"}


def test_unambiguous_alias_with_duplicate_exports_does_not_guess_call_target(
    tmp_path: Path,
) -> None:
    _write_config(
        tmp_path,
        "tsconfig.json",
        '{"baseUrl": ".", "paths": {"@/*": ["src/*"]}}',
    )
    _write(
        tmp_path,
        "src/main.ts",
        'import { duplicate } from "@/duplicate";\nexport function run() { return duplicate(); }\n',
    )
    _write(
        tmp_path,
        "src/duplicate.ts",
        "export function duplicate() { return 1; }\nexport function duplicate() { return 2; }\n",
    )

    graph = analyze_project(tmp_path)

    # The module path is unique, so the module-level import is valid. The
    # duplicate export makes the imported binding ambiguous, so no CALLS edge
    # is inferred.
    assert _module_import_targets(graph, "module:src/main.ts") == {"module:src/duplicate.ts"}
    assert not _targets(graph, "function:src/main.ts::run", "CALLS")
    assert graph.graph["metadata"]["calls_resolved"] == 0

    document = graph_to_dict(graph)
    assert document["schema_version"] == "1.0"
    assert "IMPORTS" in {relation["type"] for relation in document["relations"]}
    assert "CALLS" not in {relation["type"] for relation in document["relations"]}


def test_inherits_paths_and_base_url_from_local_config(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "configs/tsconfig.base.json",
        """{
          "compilerOptions": {
            "baseUrl": ".",
            "paths": { "@/*": ["src/*"] }
          }
        }
        """,
    )
    _write(tmp_path, "tsconfig.json", '{"extends": "./configs/tsconfig.base.json"}')
    _write(
        tmp_path,
        "src/main.ts",
        'import { feature } from "@/features/feature";\n'
        "export function run() { return feature(); }\n",
    )
    # baseUrl and its paths are defined in configs/tsconfig.base.json.
    _write(
        tmp_path,
        "configs/src/features/feature.ts",
        "export function feature() { return 1; }\n",
    )

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:src/main.ts") == {
        "module:configs/src/features/feature.ts"
    }
    assert _targets(graph, "function:src/main.ts::run", "CALLS") == {
        "function:configs/src/features/feature.ts::feature"
    }


def test_multiple_levels_of_extends_resolve_relative_to_each_config(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "configs/base.json",
        '{"compilerOptions": {"baseUrl": ".", "paths": {"@base/*": ["src/*"]}}}',
    )
    _write(
        tmp_path,
        "configs/levels/middle.json",
        '{"extends": "../base", "compilerOptions": {"strict": true}}',
    )
    _write(
        tmp_path,
        "tsconfig.json",
        '{"extends": "./configs/levels/middle.json", "compilerOptions": {"strict": false}}',
    )
    _write(
        tmp_path,
        "src/main.ts",
        'import { base } from "@base/item";\nexport function run() { return base(); }\n',
    )
    _write(tmp_path, "configs/src/item.ts", "export function base() { return 1; }\n")

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:src/main.ts") == {"module:configs/src/item.ts"}
    assert _targets(graph, "function:src/main.ts::run", "CALLS") == {
        "function:configs/src/item.ts::base"
    }


def test_child_paths_replace_parent_map_and_use_inherited_base_url(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "configs/base.json",
        '{"compilerOptions": {"baseUrl": ".", "paths": {'
        '"@base/*": ["src/base/*"], "@kept/*": ["src/kept/*"]}}}',
    )
    _write(
        tmp_path,
        "tsconfig.json",
        '{"extends": "./configs/base.json", "compilerOptions": {'
        '"paths": {"@local/*": ["src/local/*"]}}}',
    )
    _write(
        tmp_path,
        "src/main.ts",
        'import { local } from "@local/item";\n'
        'import { inherited } from "@base/item";\n'
        "export function run() { return local() + inherited(); }\n",
    )
    # TypeScript 6.0.3 resolves paths targets against the effective baseUrl,
    # even when the paths map itself is declared by the child config.
    _write(
        tmp_path,
        "configs/src/local/item.ts",
        "export function local() { return 1; }\n",
    )
    _write(tmp_path, "configs/src/base/item.ts", "export function inherited() { return 2; }\n")

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:src/main.ts") == {
        "module:configs/src/local/item.ts"
    }
    assert _targets(graph, "function:src/main.ts::run", "CALLS") == {
        "function:configs/src/local/item.ts::local"
    }
    assert graph.graph["metadata"]["unresolved_imports"] == [
        {"path": "src/main.ts", "specifier": "@base/item", "line": 2}
    ]


def test_child_base_url_overrides_inherited_value_for_inherited_paths(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "configs/base.json",
        '{"compilerOptions": {"baseUrl": ".", "paths": {"@base/*": ["src/*"]}}}',
    )
    _write(
        tmp_path,
        "tsconfig.json",
        '{"extends": "./configs/base.json", "compilerOptions": {"baseUrl": "."}}',
    )
    _write(
        tmp_path,
        "src/main.ts",
        'import { base } from "@base/item";\nexport function run() { return base(); }\n',
    )
    _write(tmp_path, "src/item.ts", "export function base() { return 1; }\n")
    _write(tmp_path, "configs/src/item.ts", "export function base() { return 2; }\n")

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:src/main.ts") == {"module:src/item.ts"}
    assert _targets(graph, "function:src/main.ts::run", "CALLS") == {"function:src/item.ts::base"}


def test_paths_without_base_url_are_relative_to_the_config_that_declares_them(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "configs/base.json",
        '{"compilerOptions": {"paths": {"@base/*": ["src/base/*"]}}}',
    )
    _write(
        tmp_path,
        "packages/app/tsconfig.json",
        '{"extends": "../../configs/base.json", "compilerOptions": {'
        '"paths": {"@app/*": ["src/app/*"]}}}',
    )
    _write(
        tmp_path,
        "packages/app/main.ts",
        'import { app } from "@app/item";\nexport function run() { return app(); }\n',
    )
    _write(
        tmp_path,
        "packages/app/src/app/item.ts",
        "export function app() { return 1; }\n",
    )

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:packages/app/main.ts") == {
        "module:packages/app/src/app/item.ts"
    }
    assert _targets(graph, "function:packages/app/main.ts::run", "CALLS") == {
        "function:packages/app/src/app/item.ts::app"
    }


def test_local_extends_array_applies_parent_configs_left_to_right(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "configs/first.json",
        '{"compilerOptions": {"baseUrl": ".", "paths": {'
        '"@value/*": ["src/first/*"], "@first-only/*": ["src/first-only/*"]}}}',
    )
    _write(
        tmp_path,
        "configs/second.json",
        '{"compilerOptions": {"paths": {"@value/*": ["src/second/*"]}}}',
    )
    _write(
        tmp_path,
        "tsconfig.json",
        '{"extends": ["./configs/first.json", "./configs/second.json"]}',
    )
    _write(
        tmp_path,
        "src/main.ts",
        'import { selected } from "@value/item";\n'
        'import { firstOnly } from "@first-only/item";\n'
        "export function run() { return selected() + firstOnly(); }\n",
    )
    _write(
        tmp_path,
        "configs/src/second/item.ts",
        "export function selected() { return 1; }\n",
    )
    _write(
        tmp_path,
        "configs/src/first-only/item.ts",
        "export function firstOnly() { return 2; }\n",
    )

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:src/main.ts") == {
        "module:configs/src/second/item.ts"
    }
    assert _targets(graph, "function:src/main.ts::run", "CALLS") == {
        "function:configs/src/second/item.ts::selected"
    }
    assert graph.graph["metadata"]["unresolved_imports"] == [
        {"path": "src/main.ts", "specifier": "@first-only/item", "line": 2}
    ]


def test_extends_cycle_fails_closed_but_keeps_relative_results(tmp_path: Path) -> None:
    _write(tmp_path, "tsconfig.json", '{"extends": "./configs/base.json"}')
    _write(tmp_path, "configs/base.json", '{"extends": "../tsconfig.json"}')
    _write(
        tmp_path,
        "src/main.ts",
        'import { local } from "./local";\n'
        'import { inherited } from "@/inherited";\n'
        "export function run() { return local() + inherited(); }\n",
    )
    _write(tmp_path, "src/local.ts", "export function local() { return 1; }\n")
    _write(tmp_path, "src/inherited.ts", "export function inherited() { return 2; }\n")

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:src/main.ts") == {"module:src/local.ts"}
    assert _targets(graph, "function:src/main.ts::run", "CALLS") == {"function:src/local.ts::local"}
    assert graph.graph["metadata"]["unresolved_imports"] == [
        {"path": "src/main.ts", "specifier": "@/inherited", "line": 2}
    ]


@pytest.mark.parametrize(
    "extends_value",
    ["./configs/missing.json", "./configs/invalid.json"],
    ids=["missing", "invalid-jsonc"],
)
def test_missing_or_invalid_extended_config_fails_closed(
    tmp_path: Path, extends_value: str
) -> None:
    _write(tmp_path, "tsconfig.json", json.dumps({"extends": extends_value}))
    _write(tmp_path, "configs/invalid.json", '{"compilerOptions": { /* unterminated')
    _write(
        tmp_path,
        "src/main.ts",
        'import { local } from "./local";\n'
        'import { inherited } from "@/inherited";\n'
        "export function run() { return local() + inherited(); }\n",
    )
    _write(tmp_path, "src/local.ts", "export function local() { return 1; }\n")
    _write(tmp_path, "src/inherited.ts", "export function inherited() { return 2; }\n")

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:src/main.ts") == {"module:src/local.ts"}
    assert _targets(graph, "function:src/main.ts::run", "CALLS") == {"function:src/local.ts::local"}
    assert graph.graph["metadata"]["unresolved_imports"] == [
        {"path": "src/main.ts", "specifier": "@/inherited", "line": 2}
    ]


def test_extends_cannot_escape_project_root(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write(project_root, "tsconfig.json", '{"extends": "../outside.json"}')
    _write(project_root, "src/main.ts", 'import { outside } from "@/outside";\n')
    _write(project_root, "src/outside.ts", "export function outside() { return 1; }\n")
    _write(tmp_path, "outside.json", '{"compilerOptions": {"baseUrl": "."}}')

    graph = analyze_project(project_root)

    assert not _module_import_targets(graph, "module:src/main.ts")
    assert graph.graph["metadata"]["unresolved_imports"] == [
        {"path": "src/main.ts", "specifier": "@/outside", "line": 1}
    ]


def test_absolute_extends_is_not_loaded(tmp_path: Path) -> None:
    external_config = tmp_path / "outside.json"
    _write(tmp_path, "tsconfig.json", json.dumps({"extends": str(external_config)}))
    _write(tmp_path, "src/main.ts", 'import { target } from "@/target";\n')
    _write(tmp_path, "src/target.ts", "export function target() { return 1; }\n")

    graph = analyze_project(tmp_path)

    assert not _module_import_targets(graph, "module:src/main.ts")
    assert graph.graph["metadata"]["unresolved_imports"] == [
        {"path": "src/main.ts", "specifier": "@/target", "line": 1}
    ]


def test_extends_cache_is_fresh_for_each_analysis(tmp_path: Path) -> None:
    _write(tmp_path, "tsconfig.json", '{"extends": "./configs/base.json"}')
    base_config = _write(
        tmp_path,
        "configs/base.json",
        '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/first/*"]}}}',
    )
    _write(tmp_path, "src/main.ts", 'import { target } from "@/item";\n')
    _write(tmp_path, "configs/src/first/item.ts", "export function target() { return 1; }\n")
    _write(tmp_path, "configs/src/second/item.ts", "export function target() { return 2; }\n")

    first = analyze_project(tmp_path)
    base_config.write_text(
        '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/second/*"]}}}',
        encoding="utf-8",
    )
    second = analyze_project(tmp_path)

    assert _module_import_targets(first, "module:src/main.ts") == {
        "module:configs/src/first/item.ts"
    }
    assert _module_import_targets(second, "module:src/main.ts") == {
        "module:configs/src/second/item.ts"
    }


def test_inherited_alias_preserves_relative_resolution_and_schema(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "configs/base.json",
        '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}',
    )
    _write(tmp_path, "tsconfig.json", '{"extends": "./configs/base.json"}')
    _write(
        tmp_path,
        "src/main.ts",
        'import { inherited } from "@/inherited";\n'
        'import { relative } from "./relative";\n'
        "export function run() { return inherited() + relative(); }\n",
    )
    _write(tmp_path, "configs/src/inherited.ts", "export function inherited() { return 1; }\n")
    _write(tmp_path, "src/relative.ts", "export function relative() { return 2; }\n")

    graph = analyze_project(tmp_path)
    document = graph_to_dict(graph)

    assert isinstance(graph, nx.MultiDiGraph)
    assert document["schema_version"] == "1.0"
    relation_keys = {
        "id",
        "source",
        "target",
        "type",
        "provenance",
        "confidence",
        "certainty",
        "origin",
        "inferred",
    }
    assert all(relation_keys == set(relation) for relation in document["relations"])
    assert _module_import_targets(graph, "module:src/main.ts") == {
        "module:configs/src/inherited.ts",
        "module:src/relative.ts",
    }
    relative_edge = next(
        data
        for _, target, data in graph.out_edges("module:src/main.ts", data=True)
        if target == "module:src/relative.ts" and data["type"] == "IMPORTS"
    )
    assert relative_edge["provenance"]["method"] == "tree-sitter+relative-path-resolution"
    assert _targets(graph, "function:src/main.ts::run", "CALLS") == {
        "function:configs/src/inherited.ts::inherited",
        "function:src/relative.ts::relative",
    }


def test_jsconfig_can_inherit_local_paths(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "configs/jsconfig.base.json",
        '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}',
    )
    _write(tmp_path, "jsconfig.json", '{"extends": "./configs/jsconfig.base.json"}')
    _write(tmp_path, "src/main.js", 'import { helper } from "@/helper";\n')
    _write(tmp_path, "configs/src/helper.js", "export function helper() { return 1; }\n")

    graph = analyze_project(tmp_path)

    assert _module_import_targets(graph, "module:src/main.js") == {"module:configs/src/helper.js"}


def test_extends_symlink_cannot_load_a_config_outside_project(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    outside_config = _write(
        tmp_path,
        "outside.json",
        '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}',
    )
    _write(project_root, "tsconfig.json", '{"extends": "./configs/shared.json"}')
    _write(project_root, "src/main.ts", 'import { outside } from "@/outside";\n')
    _write(project_root, "src/outside.ts", "export function outside() { return 1; }\n")
    link = project_root / "configs/shared.json"
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(outside_config)
    except OSError as error:
        pytest.skip(f"Symlinks are not available: {error}")

    graph = analyze_project(project_root)

    assert not _module_import_targets(graph, "module:src/main.ts")
    assert graph.graph["metadata"]["unresolved_imports"] == [
        {"path": "src/main.ts", "specifier": "@/outside", "line": 1}
    ]


def test_depth_limited_chain_does_not_poison_a_shorter_lookup(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tsconfig.json",
        '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}',
    )
    for index in range(1, 32):
        next_config = f"./c{index + 1}.json" if index < 31 else "../tsconfig.json"
        _write(tmp_path, f"chain/c{index}.json", json.dumps({"extends": next_config}))
    _write(
        tmp_path,
        "packages/app/tsconfig.json",
        '{"extends": "../../chain/c1.json"}',
    )
    _write(tmp_path, "packages/app/main.ts", 'import { target } from "@/target";\n')
    _write(tmp_path, "src/main.ts", 'import { target } from "@/target";\n')
    _write(tmp_path, "src/target.ts", "export function target() { return 1; }\n")

    graph = analyze_project(tmp_path)

    assert not _module_import_targets(graph, "module:packages/app/main.ts")
    assert _module_import_targets(graph, "module:src/main.ts") == {"module:src/target.ts"}
    assert graph.graph["metadata"]["unresolved_imports"] == [
        {"path": "packages/app/main.ts", "specifier": "@/target", "line": 1}
    ]
