"""A small reader for the frontend's TypeScript DTOs, and a validator for JSON against them.

It understands what `src/types/*.ts` uses: interfaces (with `extends`), type aliases, unions,
string literals, `T[]`, `Array<T>`, `Record<K, V>`, `Pick<T, 'a' | 'b'>`, inline object types and
`T | null`. Objects are checked strictly: a missing required field and an unexpected extra field
are both contract violations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PRIMITIVES = {"string", "number", "boolean", "null", "unknown", "any"}


def _strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"//[^\n]*", "", source)


def _split_top(text: str, separators: str) -> list[str]:
    """Split on separator characters that are not nested in <>, {}, (), [] or quotes."""
    parts, depth, current, quote = [], 0, [], ""
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            continue
        if char in "'\"":
            quote = char
        elif char in "<{([":
            depth += 1
        elif char in ">})]":
            depth -= 1
        elif char in separators and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


@dataclass
class Interface:
    name: str
    fields: dict[str, tuple[str, bool]]  # name -> (type, optional)
    extends: list[str] = field(default_factory=list)


@dataclass
class TypeRegistry:
    interfaces: dict[str, Interface] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, types_dir: Path) -> TypeRegistry:
        registry = cls()
        for path in sorted(types_dir.glob("*.ts")):
            registry._parse(_strip_comments(path.read_text(encoding="utf-8")))
        return registry

    def _parse(self, source: str) -> None:
        for match in re.finditer(
            r"export interface (\w+)(?:<[^>]*>)?(?:\s+extends\s+([\w\s,]+))?\s*\{", source
        ):
            start = match.end()
            depth, index = 1, start
            while depth:
                depth += {"{": 1, "}": -1}.get(source[index], 0)
                index += 1
            body = source[start : index - 1]
            fields = {}
            for line in _split_top(body, ";\n"):
                name, _, type_ = line.partition(":")
                name = name.strip()
                optional = name.endswith("?")
                fields[name.rstrip("?")] = (type_.strip(), optional)
            extends = [e.strip() for e in (match.group(2) or "").split(",") if e.strip()]
            self.interfaces[match.group(1)] = Interface(match.group(1), fields, extends)
        for match in re.finditer(r"export type (\w+)(?:<[^>]*>)?\s*=\s*", source):
            rest = source[match.end() :]
            # The alias runs until the next top-level statement.
            end = re.search(r"\n(?=export |\Z)", rest)
            self.aliases[match.group(1)] = (
                (rest[: end.start()] if end else rest).strip().rstrip(";")
            )

    # ------------------------------------------------------------------ validation

    def fields_of(self, name: str) -> dict[str, tuple[str, bool]]:
        interface = self.interfaces[name]
        fields: dict[str, tuple[str, bool]] = {}
        for parent in interface.extends:
            fields.update(self.fields_of(parent))
        fields.update(interface.fields)
        return fields

    def validate(self, value: Any, type_: str, path: str = "$") -> list[str]:
        type_ = type_.strip()
        while (
            type_.startswith("(")
            and type_.endswith(")")
            and len(_split_top(type_[1:-1], "|")) >= 1
            and _balanced(type_[1:-1])
        ):
            type_ = type_[1:-1].strip()
        options = _split_top(type_, "|")
        if len(options) > 1:
            attempts = [self.validate(value, option, path) for option in options]
            if any(not errors for errors in attempts):
                return []
            best = min(attempts, key=len)
            return best if len(best) < 3 else [f"{path}: {value!r:.60} matches none of {type_}"]
        if type_.endswith("[]"):
            return self._array(value, type_[:-2], path)
        generic = re.fullmatch(r"(\w+)<(.*)>", type_, flags=re.S)
        if generic:
            return self._generic(value, generic.group(1), generic.group(2), path)
        if type_.startswith("{"):
            return self._object(value, self._inline_fields(type_[1:-1]), path)
        if re.fullmatch(r"'[^']*'|\"[^\"]*\"", type_):
            return [] if value == type_[1:-1] else [f"{path}: expected {type_}, got {value!r}"]
        if type_ in {"true", "false"}:
            return (
                [] if value is (type_ == "true") else [f"{path}: expected {type_}, got {value!r}"]
            )
        if re.fullmatch(r"-?\d+(\.\d+)?", type_):
            return [] if value == float(type_) else [f"{path}: expected {type_}, got {value!r}"]
        if type_ in PRIMITIVES:
            return self._primitive(value, type_, path)
        if type_ in self.aliases:
            return self.validate(value, self.aliases[type_], path)
        if type_ in self.interfaces:
            return self._object(value, self.fields_of(type_), path)
        return [f"{path}: unknown type {type_}"]

    def _inline_fields(self, body: str) -> dict[str, tuple[str, bool]]:
        fields = {}
        for line in _split_top(body, ";\n,"):
            name, _, type_ = line.partition(":")
            fields[name.strip().rstrip("?")] = (type_.strip(), name.strip().endswith("?"))
        return fields

    def _primitive(self, value: Any, type_: str, path: str) -> list[str]:
        ok = {
            "string": isinstance(value, str),
            "number": isinstance(value, int | float) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "null": value is None,
            "unknown": True,
            "any": True,
        }[type_]
        return [] if ok else [f"{path}: expected {type_}, got {type(value).__name__}"]

    def _array(self, value: Any, item: str, path: str) -> list[str]:
        if not isinstance(value, list):
            return [f"{path}: expected an array"]
        errors: list[str] = []
        for index, element in enumerate(value):
            errors += self.validate(element, item, f"{path}[{index}]")
        return errors

    def _generic(self, value: Any, name: str, args: str, path: str) -> list[str]:
        params = _split_top(args, ",")
        if name == "Array":
            return self._array(value, params[0], path)
        if name == "Record":
            if not isinstance(value, dict):
                return [f"{path}: expected an object"]
            keys = self._literal_set(params[0])
            errors = []
            if keys is not None and set(value) != keys:
                errors.append(f"{path}: keys {sorted(value)} != {sorted(keys)}")
            for key, element in value.items():
                errors += self.validate(element, params[1], f"{path}.{key}")
            return errors
        if name == "Pick":
            wanted = self._literal_set(params[1]) or set()
            fields = {k: v for k, v in self.fields_of(params[0]).items() if k in wanted}
            return self._object(value, fields, path)
        return [f"{path}: unsupported generic {name}"]

    def _literal_set(self, type_: str) -> set[str] | None:
        type_ = self.aliases.get(type_.strip(), type_.strip())
        options = _split_top(type_, "|")
        if all(re.fullmatch(r"'[^']*'", o) for o in options):
            return {o[1:-1] for o in options}
        return None

    def _object(self, value: Any, fields: dict[str, tuple[str, bool]], path: str) -> list[str]:
        if not isinstance(value, dict):
            return [f"{path}: expected an object, got {type(value).__name__}"]
        errors = [f"{path}: unexpected field '{k}'" for k in value if k not in fields]
        for name, (type_, optional) in fields.items():
            if name not in value:
                if not optional:
                    errors.append(f"{path}: missing field '{name}'")
                continue
            errors += self.validate(value[name], type_, f"{path}.{name}")
        return errors


def _balanced(text: str) -> bool:
    depth = 0
    for char in text:
        depth += {"(": 1, ")": -1}.get(char, 0)
        if depth < 0:
            return False
    return depth == 0
