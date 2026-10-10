"""Fixtures for pyqaci-sensitive-repr: each must fire, or stay silent, as its name says."""

import astroid
import pytest
from pylint.testutils import CheckerTestCase, MessageTest, set_config

from py_qa.pylint_plugin.sensitive_repr import (
    DEFAULT_NAMES,
    SensitiveReprChecker,
    is_sensitive_name,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("password", True),
        ("db_password", True),
        ("api_key", True),
        ("apiKey", True),
        ("client_secret", True),
        ("refresh_token", True),
        ("private_key_pem", True),
        ("credentials", True),
        ("max_tokens", False),
        ("tokenizer", False),
        ("username", False),
        ("secretary", False),
    ],
)
def test_sensitive_names(name: str, *, expected: bool) -> None:
    assert is_sensitive_name(name, DEFAULT_NAMES) is expected


class TestSensitiveRepr(CheckerTestCase):
    """The checker against dataclass and pydantic shapes."""

    CHECKER_CLASS = SensitiveReprChecker

    def fires(self, code: str, field: str, owner: str, kind: str) -> None:
        module = astroid.parse(code)
        node = next(
            n
            for n in module.nodes_of_class(astroid.nodes.AnnAssign)
            if isinstance(n.target, astroid.nodes.AssignName) and n.target.name == field
        )
        with self.assertAddsMessages(
            MessageTest(
                msg_id="pyqaci-sensitive-repr",
                node=node,
                args=(owner, field, kind),
                line=node.lineno,
                col_offset=node.col_offset,
                end_line=node.end_lineno,
                end_col_offset=node.end_col_offset,
            ),
            ignore_position=False,
        ):
            self.walk(module)

    def silent(self, code: str) -> None:
        with self.assertNoMessages():
            self.walk(astroid.parse(code))

    def test_dataclass_field(self) -> None:
        code = (
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class Login:\n"
            "    user: str\n"
            "    password: str\n"
        )
        self.fires(code, "password", "Login", "dataclass")

    def test_dataclass_called_with_options_and_module_alias(self) -> None:
        code = (
            "import dataclasses as dc\n"
            "@dc.dataclass(frozen=True)\n"
            "class Client:\n"
            "    api_key: str = ''\n"
        )
        self.fires(code, "api_key", "Client", "dataclass")

    def test_pydantic_model_field(self) -> None:
        code = "class BaseModel:\n    pass\nclass Settings(BaseModel):\n    token: str\n"
        module = astroid.parse(code, module_name="pydantic.main")
        node = next(module.nodes_of_class(astroid.nodes.AnnAssign))
        with self.assertAddsMessages(
            MessageTest(
                msg_id="pyqaci-sensitive-repr",
                node=node,
                args=("Settings", "token", "pydantic model"),
            ),
            ignore_position=True,
        ):
            self.walk(module)

    def test_repr_false_is_silent(self) -> None:
        self.silent(
            "from dataclasses import dataclass, field\n"
            "@dataclass\n"
            "class Login:\n"
            "    password: str = field(repr=False)\n"
        )

    def test_dataclass_repr_off_is_silent(self) -> None:
        self.silent(
            "from dataclasses import dataclass\n"
            "@dataclass(repr=False)\n"
            "class Login:\n"
            "    password: str\n"
        )

    def test_hand_written_repr_is_silent(self) -> None:
        self.silent(
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class Login:\n"
            "    password: str\n"
            "    def __repr__(self) -> str:\n"
            "        return 'Login(<redacted>)'\n"
        )

    def test_redacting_type_is_silent(self) -> None:
        self.silent(
            "from dataclasses import dataclass\n"
            "from pydantic import SecretStr\n"
            "@dataclass\n"
            "class Login:\n"
            "    password: SecretStr | None\n"
        )

    def test_class_var_and_plain_class_are_silent(self) -> None:
        self.silent(
            "from dataclasses import dataclass\n"
            "from typing import ClassVar\n"
            "@dataclass\n"
            "class Login:\n"
            "    token_header: ClassVar[str] = 'X-Token'\n"
            "class Plain:\n"
            "    password: str\n"
        )

    def test_unrelated_decorator_is_silent(self) -> None:
        self.silent(
            "def dataclass_like(cls):\n"
            "    return cls\n"
            "@dataclass_like\n"
            "class Login:\n"
            "    password: str\n"
        )

    @set_config(pyqaci_sensitive_names=("pin",))
    def test_configured_names_replace_the_defaults(self) -> None:
        self.silent(
            "from dataclasses import dataclass\n@dataclass\nclass Login:\n    password: str\n"
        )
