"""pyqaci-broad-suppress: contextlib.suppress given Exception or BaseException."""

from __future__ import annotations

from typing import TYPE_CHECKING

from astroid import nodes
from astroid.exceptions import InferenceError
from astroid.util import UninferableBase
from pylint.checkers import BaseChecker

if TYPE_CHECKING:
    from pylint.typing import MessageDefinitionTuple

MESSAGE = "pyqaci-broad-suppress"
_BROAD = frozenset({"builtins.Exception", "builtins.BaseException"})


MESSAGES: dict[str, MessageDefinitionTuple] = {
    "W9702": (
        "contextlib.suppress(%s) hides every error raised in its block; name the exceptions "
        "the block expects (python-qa rule-doc pyqaci-broad-suppress)",
        MESSAGE,
        "Give contextlib.suppress only the exceptions its block is expected to raise, never "
        "Exception or BaseException. A broad suppress is a try/except Exception: pass in "
        "another shape: a failure inside the block disappears and the code after it runs on "
        "a state that was never reached.",
    )
}


class BroadSuppressChecker(BaseChecker):
    """Report contextlib.suppress calls that silence every error in their block."""

    name = "pyqaci-broad-suppress"
    msgs = MESSAGES

    def visit_call(self, node: nodes.Call) -> None:
        """Check each argument of a call that resolves to contextlib.suppress."""
        if _qualified_name(node.func) != "contextlib.suppress":
            return
        for argument in node.args:
            if _qualified_name(argument) in _BROAD:
                self.add_message(MESSAGE, node=node, args=(argument.as_string(),))


def _qualified_name(node: nodes.NodeNG) -> str | None:
    try:
        inferred = next(node.infer())
    except (InferenceError, StopIteration):
        return None
    if isinstance(inferred, UninferableBase) or not isinstance(inferred, nodes.ClassDef):
        return None
    return inferred.qname()
