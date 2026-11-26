"""Lexical admission for external WARA queries, never query execution."""

from __future__ import annotations

import re
from dataclasses import dataclass

ARG_TABLES = frozenset(
    {
        "advisorresources",
        "maintenanceresources",
        "recoveryservicesresources",
        "resourcecontainers",
        "resources",
    }
)


@dataclass(frozen=True)
class QueryToken:
    kind: str
    value: str


def _decode_escape(query: str, index: int) -> tuple[str, int]:
    if index + 1 >= len(query):
        raise ValueError("unterminated escape")
    escape = query[index + 1]
    simple = {
        "'": "'",
        '"': '"',
        "\\": "\\",
        "a": "\a",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
    }
    if escape in simple:
        return simple[escape], index + 2
    width = {"x": 2, "u": 4, "U": 8}.get(escape)
    if width is None:
        raise ValueError("unsupported escape")
    digits = query[index + 2 : index + 2 + width]
    if len(digits) != width or any(char not in "0123456789abcdefABCDEF" for char in digits):
        raise ValueError("malformed Unicode escape")
    try:
        return chr(int(digits, 16)), index + 2 + width
    except ValueError as exc:
        raise ValueError("invalid Unicode escape") from exc


def tokenize_query(query: str) -> tuple[QueryToken, ...]:
    """Keep code and literals distinct; reject incomplete lexical constructs."""

    tokens: list[QueryToken] = []
    delimiters: list[str] = []
    index = 0
    line_has_code = False
    while index < len(query):
        char = query[index]
        if char.isspace():
            if char in "\r\n\u0085\u2028\u2029":
                line_has_code = False
            index += 1
            continue
        if query.startswith("//", index):
            index += 2
            while index < len(query) and query[index] not in "\r\n\u0085\u2028\u2029":
                index += 1
            continue
        if query.startswith("/*", index):
            depth = 1
            index += 2
            while index < len(query) and depth:
                if query.startswith("/*", index):
                    depth += 1
                    index += 2
                elif query.startswith("*/", index):
                    depth -= 1
                    index += 2
                else:
                    if query[index] in "\r\n\u0085\u2028\u2029":
                        line_has_code = False
                    index += 1
            if depth:
                raise ValueError("unterminated comment")
            continue
        if query.startswith("```", index):
            end = query.find("```", index + 3)
            if end < 0:
                raise ValueError("unterminated multiline string")
            tokens.append(QueryToken("string", query[index + 3 : end]))
            line_has_code = True
            index = end + 3
            continue
        verbatim = char == "@" and query[index + 1 : index + 2] in {"'", '"'}
        if char in {"'", '"'} or verbatim:
            if verbatim:
                index += 1
            quote = query[index]
            index += 1
            value: list[str] = []
            while index < len(query):
                char = query[index]
                if char == quote:
                    if verbatim and query[index + 1 : index + 2] == quote:
                        value.append(quote)
                        index += 2
                        continue
                    index += 1
                    break
                if char == "\\" and not verbatim:
                    decoded, index = _decode_escape(query, index)
                    value.append(decoded)
                    continue
                if char in "\r\n" and not verbatim:
                    raise ValueError("newline in quoted string")
                value.append(char)
                index += 1
            else:
                raise ValueError("unterminated quoted string")
            tokens.append(QueryToken("string", "".join(value)))
            line_has_code = True
            continue
        if char.isascii() and (char.isalpha() or char == "_"):
            end = index + 1
            while (
                end < len(query)
                and query[end].isascii()
                and (query[end].isalnum() or query[end] == "_")
            ):
                end += 1
            tokens.append(QueryToken("identifier", query[index:end].casefold()))
            line_has_code = True
            index = end
            continue
        if char in "([{":
            delimiters.append(char)
        elif char in ")]}":
            if not delimiters or delimiters.pop() != {")": "(", "]": "[", "}": "{"}[char]:
                raise ValueError("unbalanced delimiters")
        if not char.isascii() or (ord(char) < 32 and not char.isspace()):
            raise ValueError("unsupported code character")
        if not (char.isdigit() or char in ".|;,:()[]{}=!?~<>+-*/%&^$"):
            raise ValueError("unsupported code character")
        kind = "control_prefix" if char == "." and not line_has_code else "symbol"
        tokens.append(QueryToken(kind, char))
        line_has_code = True
        index += 1
    if delimiters:
        raise ValueError("unbalanced delimiters")
    return tuple(tokens)


def lexical_review(tokens: tuple[QueryToken, ...]) -> tuple[set[str], tuple[str, ...]]:
    """Conservatively reject commands and unreviewed cross-source expressions."""

    reasons: set[str] = set()
    tables: set[str] = set()
    command_position = True
    for index, token in enumerate(tokens):
        if token.kind == "identifier":
            word = token.value
            if word in ARG_TABLES:
                tables.add(word)
            if (
                word in {"externaldata", "http_request", "cluster", "database"}
                and index + 1 < len(tokens)
                and tokens[index + 1].value == "("
            ):
                reasons.add("dynamic_endpoint")
            if command_position and word in {
                "delete",
                "drop",
                "alter",
                "create",
                "update",
                "patch",
            }:
                reasons.add("mutation_command")
            if command_position and word in {"set", "execute", "invoke"}:
                reasons.add("control_command")
            if command_position and word in {"join", "union"}:
                reasons.add("unsupported_join")
        if (
            token.kind == "string"
            and token.value.casefold() in {"externaldata", "http_request", "cluster", "database"}
            and index > 0
            and tokens[index - 1].value == "["
            and tuple(item.value for item in tokens[index + 1 : index + 3]) == ("]", "(")
        ):
            reasons.add("dynamic_endpoint")
        if token.value == ";" and token.kind == "symbol":
            reasons.add("multiple_statements")
        if token.kind == "control_prefix" or (
            token.kind == "symbol" and token.value == "." and command_position
        ):
            reasons.add("control_command")
        command_position = token.kind == "control_prefix" or (
            token.kind == "symbol"
            and (token.value in {"|", ";"} or (token.value == "." and command_position))
        )
    if (
        tokens
        and tokens[-1].kind in {"symbol", "control_prefix"}
        and tokens[-1].value in {"|", "."}
    ):
        reasons.add("malformed_query")
    if not tokens or tokens[0].kind != "identifier" or tokens[0].value not in ARG_TABLES:
        reasons.add("missing_declared_table")
    return reasons, tuple(sorted(tables))


def source_resource_types(tokens: tuple[QueryToken, ...]) -> tuple[str, ...]:
    """Read source type predicates, not comments, labels or resource-id properties."""

    resource_types: set[str] = set()
    pattern = r"(?i)\b(?:microsoft|oracle)\.[a-z0-9.]+(?:/[a-z0-9._-]+)+"
    for index, token in enumerate(tokens):
        if token.kind == "identifier" and token.value == "type":
            end = index + 1
            start = index
        elif (
            token.kind == "string"
            and token.value.casefold() == "type"
            and index > 0
            and tokens[index - 1].value == "["
            and index + 1 < len(tokens)
            and tokens[index + 1].value == "]"
        ):
            start = index - 1
            end = index + 2
        else:
            continue
        if start > 0 and tokens[start - 1].value == ".":
            continue
        if (
            token.kind == "string"
            and start > 0
            and tokens[start - 1].kind == "identifier"
            and tokens[start - 1].value not in {"where", "and", "or"}
        ):
            continue
        if end >= len(tokens) or tokens[end].value not in {
            "=",
            "!",
            "<",
            ">",
            "in",
            "in_cs",
            "has",
            "contains",
            "startswith",
            "endswith",
        }:
            continue
        for candidate in tokens[end:]:
            if (candidate.kind == "symbol" and candidate.value in {"|", ";"}) or (
                candidate.kind == "identifier" and candidate.value in {"and", "or"}
            ):
                break
            if candidate.kind == "string":
                resource_types.update(
                    match.casefold() for match in re.findall(pattern, candidate.value)
                )
    return tuple(sorted(resource_types))
