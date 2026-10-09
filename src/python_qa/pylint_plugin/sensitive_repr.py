"""pyqaci-sensitive-repr: a credential-named field printed by a generated __repr__."""

from __future__ import annotations

import re

from astroid import nodes
from astroid.exceptions import InferenceError
from astroid.util import UninferableBase
from pylint.checkers import BaseChecker

MESSAGE = "pyqaci-sensitive-repr"
DEFAULT_NAMES = (
    "password",
    "passwd",
    "passphrase",
    "secret",
    "token",
    "credential",
    "credentials",
    "apikey",
    "api_key",
    "private_key",
    "access_key",
    "secret_key",
)
DEFAULT_REDACTING_TYPES = ("SecretStr", "SecretBytes", "Secret")
_DATACLASS_DECORATORS = frozenset({"dataclasses.dataclass", "pydantic.dataclasses.dataclass"})
_PYDANTIC_BASES = frozenset({"pydantic.main.BaseModel", "pydantic.BaseModel"})


def is_sensitive_name(name: str, patterns: tuple[str, ...] | list[str]) -> bool:
    """Return True when a word of name, or a run of its words, is one of the patterns.

    Names are split into words at underscores and at lower-to-upper case changes, so `apiKey`
    is `api key`. A pattern with an underscore matches consecutive words; any other matches one
    whole word, so `token` matches `refresh_token` but not `max_tokens` or `tokenizer`.
    """
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower().strip("_").split("_")
    joined = "_" + "_".join(words) + "_"
    return any(
        f"_{pattern.lower()}_" in joined if "_" in pattern else pattern.lower() in words
        for pattern in patterns
    )


class SensitiveReprChecker(BaseChecker):
    """Report credential-named fields that a dataclass or pydantic model prints in its repr."""

    name = "pyqaci-sensitive-repr"
    msgs = {
        "W9701": (
            "%s.%s is printed by the generated __repr__ of a %s; exclude it with repr=False or "
            "hold it in a redacting type (python-qa rule-doc pyqaci-sensitive-repr)",
            MESSAGE,
            "A field whose name marks it as a credential is printed verbatim by the __repr__ a "
            "dataclass or pydantic model generates, so the secret reaches logs, tracebacks and "
            "test output. Declare the field with repr=False, hold it in a redacting type such as "
            "pydantic.SecretStr, or write __repr__ by hand.",
        )
    }
    options = (
        (
            "pyqaci-sensitive-names",
            {
                "type": "csv",
                "default": DEFAULT_NAMES,
                "metavar": "<names>",
                "help": "Field-name words (or underscore-joined runs) that mark a credential.",
            },
        ),
        (
            "pyqaci-redacting-types",
            {
                "type": "csv",
                "default": DEFAULT_REDACTING_TYPES,
                "metavar": "<types>",
                "help": "Simple names of types whose repr is known to redact.",
            },
        ),
    )

    def visit_classdef(self, node: nodes.ClassDef) -> None:
        """Check each annotated field of a class whose __repr__ is generated."""
        kind = _generated_repr_kind(node)
        if kind is None or "__repr__" in node.locals:
            return
        names = tuple(self.linter.config.pyqaci_sensitive_names)
        redacting = frozenset(self.linter.config.pyqaci_redacting_types)
        for statement in node.body:
            if not isinstance(statement, nodes.AnnAssign):
                continue
            target = statement.target
            if not isinstance(target, nodes.AssignName):
                continue
            if kind == "pydantic model" and target.name.startswith("_"):
                continue
            if not is_sensitive_name(target.name, names):
                continue
            if _annotation_names(statement.annotation) & (redacting | {"ClassVar"}):
                continue
            if _repr_false(statement.value):
                continue
            self.add_message(MESSAGE, node=statement, args=(node.name, target.name, kind))


def _generated_repr_kind(node: nodes.ClassDef) -> str | None:
    for decorator in node.decorators.nodes if node.decorators else []:
        func = decorator.func if isinstance(decorator, nodes.Call) else decorator
        if _qualified_name(func) in _DATACLASS_DECORATORS:
            if isinstance(decorator, nodes.Call) and _repr_false(decorator):
                return None
            return "dataclass"
    try:
        ancestors = {ancestor.qname() for ancestor in node.ancestors()}
    except InferenceError:
        return None
    return "pydantic model" if ancestors & _PYDANTIC_BASES else None


def _qualified_name(node: nodes.NodeNG) -> str | None:
    try:
        inferred = next(node.infer())
    except (InferenceError, StopIteration):
        return None
    if isinstance(inferred, UninferableBase):
        return None
    if isinstance(inferred, nodes.FunctionDef | nodes.ClassDef):
        return inferred.qname()
    return None


def _annotation_names(annotation: nodes.NodeNG | None) -> set[str]:
    if annotation is None:
        return set()
    names = {n.name for n in annotation.nodes_of_class(nodes.Name)}
    names.update(n.attrname for n in annotation.nodes_of_class(nodes.Attribute))
    return names


def _repr_false(value: nodes.NodeNG | None) -> bool:
    if not isinstance(value, nodes.Call):
        return False
    return any(
        keyword.arg == "repr"
        and isinstance(keyword.value, nodes.Const)
        and keyword.value.value is False
        for keyword in value.keywords or []
    )
