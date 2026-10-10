"""The bundled plugin registers every bundled checker with Pylint."""

from pylint.lint import PyLinter

from py_qa.pylint_plugin import BUNDLED_MESSAGES, register


def test_register_adds_every_bundled_message() -> None:
    linter = PyLinter()
    register(linter)
    for symbol in BUNDLED_MESSAGES:
        assert linter.msgs_store.get_message_definitions(symbol)
