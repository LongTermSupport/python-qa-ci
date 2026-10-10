"""Fixtures for pyqaci-broad-suppress: each must fire, or stay silent, as its name says."""

import astroid
from pylint.testutils import CheckerTestCase, MessageTest

from py_qa.pylint_plugin.broad_suppress import BroadSuppressChecker


class TestBroadSuppress(CheckerTestCase):
    """The checker against the ways contextlib.suppress is reached and called."""

    CHECKER_CLASS = BroadSuppressChecker

    def fires(self, code: str, *args: str) -> None:
        module = astroid.parse(code)
        call = next(module.nodes_of_class(astroid.nodes.With)).items[0][0]
        with self.assertAddsMessages(
            *[MessageTest(msg_id="pyqaci-broad-suppress", node=call, args=(arg,)) for arg in args],
            ignore_position=True,
        ):
            self.walk(module)

    def silent(self, code: str) -> None:
        with self.assertNoMessages():
            self.walk(astroid.parse(code))

    def test_exception(self) -> None:
        self.fires(
            "import contextlib\nwith contextlib.suppress(Exception):\n    pass\n", "Exception"
        )

    def test_base_exception_through_an_alias(self) -> None:
        self.fires(
            "from contextlib import suppress as quiet\nwith quiet(OSError, BaseException):\n"
            "    pass\n",
            "BaseException",
        )

    def test_builtins_module_form(self) -> None:
        self.fires(
            "import builtins, contextlib\nwith contextlib.suppress(builtins.Exception):\n"
            "    pass\n",
            "builtins.Exception",
        )

    def test_narrow_exception_is_silent(self) -> None:
        self.silent("import contextlib\nwith contextlib.suppress(FileNotFoundError):\n    pass\n")

    def test_shadowed_exception_name_is_silent(self) -> None:
        self.silent(
            "import contextlib\nclass Exception(ValueError):\n    pass\n"
            "with contextlib.suppress(Exception):\n    pass\n"
        )

    def test_unrelated_suppress_is_silent(self) -> None:
        self.silent("def suppress(*a):\n    return a\nsuppress(Exception)\n")
