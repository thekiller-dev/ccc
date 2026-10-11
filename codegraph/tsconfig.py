"""Safe, deliberately limited support for local TS/JS path configuration.

Configuration files are read as static JSONC. This module never evaluates
configuration code, resolves package-based ``extends``, or follows project
references; it only follows confined local relative ``extends`` chains. Its
caches live only for one project analysis.
"""

from __future__ import annotations

import json
import posixpath
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .scanner import IGNORED_DIRECTORIES

_MAX_CONFIG_SIZE_BYTES = 1_000_000
_MAX_EXTENDS_DEPTH = 32
_CONFIG_FILENAMES = ("tsconfig.json", "jsconfig.json")
_CONFIG_SUFFIXES = {".json", ".jsonc"}


@dataclass(frozen=True, slots=True)
class _PathRule:
    pattern: str
    targets: tuple[str, ...]
    prefix: str
    suffix: str
    wildcard: bool


@dataclass(frozen=True, slots=True)
class _ConfigLayer:
    config_dir: str
    extends: tuple[str, ...]
    base_url: str | None
    paths: tuple[_PathRule, ...] | None


@dataclass(frozen=True, slots=True)
class ProjectPathConfig:
    """The effective subset of one local TS/JS configuration chain."""

    base_url: str | None
    paths_base_dir: str
    paths: tuple[_PathRule, ...] | None
    chain_depth: int = 1

    def candidate_bases(self, specifier: str) -> tuple[str, ...]:
        """Return ordered project-relative targets for a non-relative import.

        Exact aliases win. Otherwise, a wildcard with the longest literal
        prefix wins; ties are rejected rather than guessed. Targets in an
        array retain their declared order. TypeScript uses the effective
        ``baseUrl`` when present; without one, path targets are relative to the
        config file that supplied the effective ``paths`` map.
        """

        if not _is_bare_specifier(specifier):
            return ()

        rules = self.paths or ()
        exact = next(
            (rule for rule in rules if not rule.wildcard and rule.pattern == specifier),
            None,
        )
        if exact is not None:
            return self._expand_targets(exact, "")

        matches: list[tuple[_PathRule, str]] = []
        for rule in rules:
            if not rule.wildcard or not specifier.startswith(rule.prefix):
                continue
            if rule.suffix and not specifier.endswith(rule.suffix):
                continue
            capture_end = len(specifier) - len(rule.suffix) if rule.suffix else len(specifier)
            if capture_end < len(rule.prefix):
                continue
            matches.append((rule, specifier[len(rule.prefix) : capture_end]))

        if matches:
            longest_prefix = max(len(rule.prefix) for rule, _ in matches)
            best_matches = [
                (rule, capture) for rule, capture in matches if len(rule.prefix) == longest_prefix
            ]
            if len(best_matches) != 1:
                # Equal-priority overlapping wildcards can select different
                # source files. Do not infer an edge from mapping order alone.
                return ()
            rule, capture = best_matches[0]
            return self._expand_targets(rule, capture)

        if self.base_url is None:
            return ()
        return _normalize_targets(self.base_url, (specifier,))

    def _expand_targets(self, rule: _PathRule, capture: str) -> tuple[str, ...]:
        base = self.base_url if self.base_url is not None else self.paths_base_dir
        targets = tuple(target.replace("*", capture) for target in rule.targets)
        return _normalize_targets(base, targets)


@dataclass(slots=True)
class _MergedPathOptions:
    base_url: str | None = None
    paths_base_dir: str = ""
    paths: tuple[_PathRule, ...] | None = None

    def apply_parent(self, parent: ProjectPathConfig) -> None:
        if parent.base_url is not None:
            self.base_url = parent.base_url
        if parent.paths is not None:
            self.paths_base_dir = parent.paths_base_dir
            self.paths = parent.paths

    def apply_layer(self, layer: _ConfigLayer) -> None:
        if layer.base_url is not None:
            self.base_url = layer.base_url
        if layer.paths is not None:
            # ``compilerOptions.paths`` is one compiler option: a child map
            # replaces the inherited map rather than merging its keys.
            self.paths_base_dir = layer.config_dir
            self.paths = layer.paths


def _is_bare_specifier(specifier: str) -> bool:
    return bool(specifier) and not (
        specifier.startswith((".", "/", "\\"))
        or "?" in specifier
        or "#" in specifier
        or "\\" in specifier
    )


def _strip_jsonc_comments(text: str) -> str:
    """Strip JSONC comments while preserving strings and line boundaries."""

    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        character = text[index]
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue

        if character == '"':
            in_string = True
            output.append(character)
            index += 1
            continue
        if character == "/" and index + 1 < len(text) and text[index + 1] == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        if character == "/" and index + 1 < len(text) and text[index + 1] == "*":
            index += 2
            while index + 1 < len(text) and text[index : index + 2] != "*/":
                if text[index] in "\r\n":
                    output.append(text[index])
                index += 1
            if index + 1 >= len(text):
                raise ValueError("Unterminated JSONC comment")
            index += 2
            continue

        output.append(character)
        index += 1
    return "".join(output)


def _remove_trailing_commas(text: str) -> str:
    """Remove commas immediately before a JSON object/array close token."""

    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        character = text[index]
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            output.append(character)
            index += 1
            continue
        if character == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "]}":
                index += 1
                continue
        output.append(character)
        index += 1
    return "".join(output)


def _normalize_project_path(base: str, value: str) -> str | None:
    """Normalize a config path and reject absolute or root-escaping targets."""

    if not value or "?" in value or "#" in value:
        return None
    normalized_value = value.replace("\\", "/")
    if normalized_value.startswith("/") or (
        len(normalized_value) >= 2 and normalized_value[1] == ":"
    ):
        return None
    combined = posixpath.normpath(posixpath.join(base, normalized_value))
    if combined == ".":
        return ""
    if combined == ".." or combined.startswith("../") or combined.startswith("/"):
        return None
    return combined


def _is_relative_config_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return bool(value) and not (
        "?" in value
        or "#" in value
        or normalized.startswith("/")
        or (len(normalized) >= 2 and normalized[1] == ":")
    )


def _normalize_targets(base: str, values: tuple[str, ...]) -> tuple[str, ...]:
    candidates: list[str] = []
    for value in values:
        normalized = _normalize_project_path(base, value)
        if normalized is not None and normalized not in candidates:
            candidates.append(normalized)
    return tuple(candidates)


def _parse_path_rules(value: Any) -> tuple[_PathRule, ...] | None:
    if not isinstance(value, dict):
        return None

    rules: list[_PathRule] = []
    for pattern, targets_value in value.items():
        if not isinstance(pattern, str) or not pattern or not _is_bare_specifier(pattern):
            return None
        if not isinstance(targets_value, list) or not targets_value:
            return None
        if any(
            not isinstance(target, str) or not _is_relative_config_path(target)
            for target in targets_value
        ):
            return None

        wildcard = "*" in pattern
        if pattern.count("*") > 1:
            return None
        if wildcard:
            prefix, _, suffix = pattern.partition("*")
            if any(target.count("*") != 1 for target in targets_value):
                return None
        else:
            prefix, suffix = pattern, ""
            if any("*" in target for target in targets_value):
                return None
        rules.append(_PathRule(pattern, tuple(targets_value), prefix, suffix, wildcard))
    return tuple(rules)


def _parse_config_layer(document: Any, config_dir: str) -> _ConfigLayer | None:
    if not isinstance(document, dict) or "references" in document:
        return None

    extends_value = document.get("extends", ())
    if isinstance(extends_value, str):
        extends = (extends_value,)
    elif isinstance(extends_value, list) and all(isinstance(item, str) for item in extends_value):
        extends = tuple(extends_value)
    elif extends_value == () and "extends" not in document:
        extends = ()
    else:
        return None

    compiler_options = document.get("compilerOptions", {})
    if not isinstance(compiler_options, dict):
        return None

    base_url: str | None = None
    if "baseUrl" in compiler_options:
        base_url_value = compiler_options["baseUrl"]
        if not isinstance(base_url_value, str):
            return None
        # TypeScript treats an empty baseUrl as the config directory.
        base_url = _normalize_project_path(config_dir, base_url_value or ".")
        if base_url is None:
            return None

    paths: tuple[_PathRule, ...] | None = None
    if "paths" in compiler_options:
        paths = _parse_path_rules(compiler_options["paths"])
        if paths is None:
            return None

    return _ConfigLayer(config_dir, extends, base_url, paths)


def _parse_jsonc(text: str) -> Any:
    uncommented = _strip_jsonc_comments(text)
    return json.loads(_remove_trailing_commas(uncommented), object_pairs_hook=_unique_object)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSONC object key")
        result[key] = value
    return result


def _effective_paths_are_in_root(options: _MergedPathOptions) -> bool:
    if options.paths is None:
        return True
    base = options.base_url if options.base_url is not None else options.paths_base_dir
    for rule in options.paths:
        for target in rule.targets:
            sample = target.replace("*", "codegraph-placeholder")
            if _normalize_project_path(base, sample) is None:
                return False
    return True


class ProjectPathConfigResolver:
    """Find and cache the nearest safe config and its local ``extends`` chain.

    The instance is created by one ``analyze_project`` call; no parsed config
    survives into later scans.
    """

    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root).resolve()
        self._layer_cache: dict[str, _ConfigLayer | None] = {}
        # Cache only complete valid chains. A failed lookup can depend on the
        # active chain (cycle/depth limit) and must not poison a shorter lookup.
        self._config_cache: dict[str, ProjectPathConfig] = {}
        self._file_cache: dict[str, ProjectPathConfig | None] = {}

    def for_file(self, importer_path: str) -> ProjectPathConfig | None:
        relative = PurePosixPath(importer_path)
        if relative.is_absolute() or ".." in relative.parts:
            return None
        normalized_path = relative.as_posix()
        if normalized_path in self._file_cache:
            return self._file_cache[normalized_path]

        config_path = self._nearest_config_path(relative.parent)
        config = self._load_effective_config(config_path, ()) if config_path is not None else None
        self._file_cache[normalized_path] = config
        return config

    def _nearest_config_path(self, directory: PurePosixPath) -> PurePosixPath | None:
        current = directory
        while True:
            # Prefer tsconfig when both files are present in the same directory.
            for filename in _CONFIG_FILENAMES:
                relative = current / filename
                candidate = self.root.joinpath(*relative.parts)
                try:
                    candidate.lstat()
                except FileNotFoundError:
                    continue
                except OSError:
                    return relative
                return relative
            if current == PurePosixPath("."):
                return None
            current = current.parent

    def _resolve_extends_path(
        self, declaring_config: PurePosixPath, specifier: str
    ) -> PurePosixPath | None:
        # Package names, absolute paths, and non-JSON config formats are out of
        # scope. Only explicit local relative paths (optionally without .json)
        # can enter the chain.
        if not specifier.startswith(("./", "../")) or "\\" in specifier:
            return None
        normalized = _normalize_project_path(declaring_config.parent.as_posix(), specifier)
        if normalized is None or not normalized:
            return None

        suffix = PurePosixPath(normalized).suffix.lower()
        if not suffix:
            normalized += ".json"
        elif suffix not in _CONFIG_SUFFIXES:
            return None

        relative = PurePosixPath(normalized)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or self._uses_ignored_directory(relative)
        ):
            return None
        return relative

    @staticmethod
    def _uses_ignored_directory(relative: PurePosixPath) -> bool:
        return any(part.lower() in IGNORED_DIRECTORIES for part in relative.parts[:-1])

    def _load_effective_config(
        self, relative: PurePosixPath, active_chain: tuple[str, ...]
    ) -> ProjectPathConfig | None:
        key = relative.as_posix()
        if key in active_chain:
            return None
        cached = self._config_cache.get(key)
        if cached is not None:
            if len(active_chain) + cached.chain_depth <= _MAX_EXTENDS_DEPTH:
                return cached
            return None
        if len(active_chain) >= _MAX_EXTENDS_DEPTH:
            return None

        layer = self._load_config_layer(relative)
        if layer is None:
            return None

        merged = _MergedPathOptions()
        chain_depth = 1
        next_chain = (*active_chain, key)
        for specifier in layer.extends:
            parent_path = self._resolve_extends_path(relative, specifier)
            if parent_path is None:
                return None
            parent = self._load_effective_config(parent_path, next_chain)
            if parent is None:
                return None
            chain_depth = max(chain_depth, parent.chain_depth + 1)
            if len(active_chain) + chain_depth > _MAX_EXTENDS_DEPTH:
                return None
            merged.apply_parent(parent)
        merged.apply_layer(layer)
        if not _effective_paths_are_in_root(merged):
            return None

        effective = ProjectPathConfig(
            merged.base_url, merged.paths_base_dir, merged.paths, chain_depth
        )
        self._config_cache[key] = effective
        return effective

    def _load_config_layer(self, relative: PurePosixPath) -> _ConfigLayer | None:
        key = relative.as_posix()
        if key in self._layer_cache:
            return self._layer_cache[key]
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or self._uses_ignored_directory(relative)
            or PurePosixPath(relative.name).suffix.lower() not in _CONFIG_SUFFIXES
        ):
            self._layer_cache[key] = None
            return None

        candidate = self.root.joinpath(*relative.parts)
        try:
            current = self.root
            metadata = None
            for index, part in enumerate(relative.parts):
                current = current / part
                metadata = current.lstat()
                if stat.S_ISLNK(metadata.st_mode):
                    self._layer_cache[key] = None
                    return None
                if index < len(relative.parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
                    self._layer_cache[key] = None
                    return None
            if metadata is None or not stat.S_ISREG(metadata.st_mode):
                self._layer_cache[key] = None
                return None
            if metadata.st_size > _MAX_CONFIG_SIZE_BYTES:
                self._layer_cache[key] = None
                return None
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(self.root):
                self._layer_cache[key] = None
                return None
            content = candidate.read_bytes()
            if len(content) > _MAX_CONFIG_SIZE_BYTES:
                self._layer_cache[key] = None
                return None
            document = _parse_jsonc(content.decode("utf-8-sig"))
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
            self._layer_cache[key] = None
            return None

        config_dir = relative.parent.as_posix()
        if config_dir == ".":
            config_dir = ""
        layer = _parse_config_layer(document, config_dir)
        self._layer_cache[key] = layer
        return layer
