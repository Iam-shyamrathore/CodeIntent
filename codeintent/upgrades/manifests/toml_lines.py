"""Recover 1-based source lines for values read with ``tomllib``, which discards positions.

Approach adapted from osv-scalibr's lockfile line lookup (Apache-2.0): scan the raw text by
section, then match decoded string tokens and keys back to the lines they appear on.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field

_HEADER = re.compile(r"^\s*(\[\[?)\s*(?P<path>[^\[\]]+?)\s*\]\]?\s*(?:#.*)?$")
_KEY = re.compile(r"""^\s*(?P<key>"(?:[^"\\]|\\.)*"|'[^']*'|[A-Za-z0-9_\-]+)\s*=""")
_STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'[^\'\n]*\'')


def _decode(token: str) -> str | None:
    try:
        return tomllib.loads(f"v = {token}")["v"]
    except tomllib.TOMLDecodeError:
        return None


def _path(header: str) -> tuple[str, ...]:
    try:
        node = tomllib.loads(f"[{header}]\n")
    except tomllib.TOMLDecodeError:
        return (header,)
    parts = []
    while isinstance(node, dict) and len(node) == 1:
        key, node = next(iter(node.items()))
        parts.append(key)
    return tuple(parts)


@dataclass
class Section:
    path: tuple[str, ...]
    keys: dict[str, int] = field(default_factory=dict)
    strings: dict[str, list[tuple[int, str]]] = field(default_factory=dict)


class TomlLines:
    def __init__(self, text: str):
        self.sections: list[Section] = [Section(())]
        key = None
        for number, line in enumerate(text.splitlines(), start=1):
            header = _HEADER.match(line)
            if header:
                self.sections.append(Section(_path(header["path"])))
                key = None
                continue
            section = self.sections[-1]
            start = 0
            match = _KEY.match(line)
            if match:
                key = (
                    _decode(match["key"]) if match["key"][0] in "\"'" else match["key"]
                )
                section.keys.setdefault(key, number)
                start = match.end()
            if key is None:
                continue
            for token in _STRING.finditer(line, start):
                value = _decode(token.group())
                if value is not None:
                    section.strings.setdefault(key, []).append((number, value))
        self._used: set[tuple[int, int, str]] = set()

    def tables(self, path: tuple[str, ...]) -> list[Section]:
        return [s for s in self.sections if s.path == path]

    def key(self, path: tuple[str, ...], key: str) -> int | None:
        for section in self.tables(path):
            if key in section.keys:
                return section.keys[key]
        return None

    def string(self, path: tuple[str, ...], key: str, value: str) -> int | None:
        """Line of ``value`` inside ``key`` in table ``path``; repeated values map to successive lines."""
        for index, section in enumerate(self.tables(path)):
            for number, candidate in section.strings.get(key, []):
                marker = (index, number, value)
                if candidate == value and marker not in self._used:
                    self._used.add(marker)
                    return number
        return None
