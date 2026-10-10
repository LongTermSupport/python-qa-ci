"""Which tests a change can affect, read from the project's import and file-reference graph.

Every Python file is parsed for its imports and its string constants. An edge runs from a file to
each project module it imports, absolute or relative; to each module a dotted string names, such
as a `mock.patch` target or an `importlib.import_module` argument; and to each project file a
string names by its path, by a path suffix, or by a file name no other file shares. Importing a
submodule also runs its enclosing packages' __init__, so that is an edge too, but an implicit
one: it carries a change to the __init__ itself to the importer, and nothing the __init__ merely
imports, which would make every package's re-exports reach every importer of the package. A
test file depends implicitly in the same way on every conftest.py above it: a change to the
conftest reaches the tests below it, and a change to what the conftest imports reaches the tests
that import it themselves. The tests a change can affect are the test files from which a changed
file is reachable.

What the graph cannot see is declared: `[[tool.py-qa.diff.map]]` names the tests for files read
by glob or by a computed name, `full_tests_on` the files whose change can affect any test, and
`unmapped` what to do about a changed file that is neither Python nor reached nor declared. Where
it is unsure the graph over-selects: an ambiguous name reaches every file it could mean. It
cannot see a module loaded by a name built at run time, which is why a diff run is the quick
check before the full run, and the full run stays the gate.

Parsing is most of the cost, so each file's imports and strings are cached by size and
modification time under the git directory, and files not in the cache are parsed in parallel.
"""

from __future__ import annotations

import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from py_qa import __version__
from py_qa.config import DiffMapEntry, read_pyproject
from py_qa.globs import match_any, match_glob
from py_qa.suppression import SKIPPED_DIRECTORIES, in_git_work_tree

if TYPE_CHECKING:
    from collections.abc import Callable

    from py_qa.config import Config
    from py_qa.diff import Change

_DEFAULT_TEST_FILES = ("test_*.py", "*_test.py")
# A string longer than this is data, not prose that might name a file.
_MAX_STRING_LENGTH = 2000
# A word in a string that could be a path or a file name.
_PATH_WORD = re.compile(r"[\w./-]*[./][\w./-]*")
# Bumped when what a scan records changes, so a cache written before is not read.
_SCAN_FORMAT = 2
# How one file reaches another, weakest first: named in prose; loaded implicitly, as a package's
# __init__ or a conftest; imported or named outright.
WEAK, IMPLICIT, EXPLICIT = range(3)
# Below this many files to parse, starting worker processes costs more than it saves.
PARALLEL_THRESHOLD = 64
# A cache entry is [stamp, imports, strings]; an import is [module, level, names].
_ENTRY_FIELDS = 3
_IMPORT_FIELDS = 3

Import = tuple[str, int, tuple[str, ...]]
Scan = tuple[list[Import], list[str]]


@dataclass(frozen=True)
class Selection:
    """The tests a change can affect, and every changed file the graph could not account for."""

    full: bool
    full_reasons: tuple[str, ...]
    tests: tuple[str, ...]
    reached_by: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unmapped: tuple[str, ...] = ()
    untested: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()


def scan_source(text: str) -> Scan:
    """Return a module's imports, as (module, level, names), and the strings that could be names.

    Source that cannot be parsed has neither; the format and detector lanes report it.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return [], []
    imports: list[Import] = []
    strings: list[str] = []
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    for node in ast.walk(tree):
        if id(node) in docstrings:
            continue
        if isinstance(node, ast.Import):
            imports.extend((alias.name, 0, ()) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names = tuple(alias.name for alias in node.names if alias.name != "*")
            imports.append((node.module or "", node.level, names))
        elif (value := _name_like(node)) is not None:
            strings.append(value)
    return imports, strings


def _name_like(node: ast.AST) -> str | None:
    """Return a string constant short and shaped enough to name a module or a file, or None."""
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return None
    value = node.value
    if len(value) > _MAX_STRING_LENGTH or not ("." in value or "/" in value):
        return None
    return value


def _scan_file(path: str) -> Scan:
    try:
        return scan_source(Path(path).read_text(encoding="utf-8"))
    except (UnicodeDecodeError, OSError):
        return [], []


def git_path(root: Path, name: str) -> Path | None:
    """Return a path inside the work tree's git directory, or None outside a git work tree."""
    if not in_git_work_tree(root):
        return None
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-path", name],
        capture_output=True,
        text=True,
        check=False,
    )
    return root / result.stdout.strip() if result.returncode == 0 else None


def _cache_version() -> str:
    return f"{__version__}/{_SCAN_FORMAT}"


def _cached_scan(entry: object, stamp: list[int]) -> Scan | None:
    """Return the scan a cache entry holds when it is well formed and its stamp still holds."""
    if not isinstance(entry, list) or len(entry) != _ENTRY_FIELDS or entry[0] != stamp:
        return None
    raw_imports, raw_strings = entry[1], entry[2]
    if not isinstance(raw_imports, list) or not isinstance(raw_strings, list):
        return None
    imports: list[Import] = []
    for item in raw_imports:
        if not (isinstance(item, list) and len(item) == _IMPORT_FIELDS):
            return None
        module, level, names = item
        if not (isinstance(module, str) and isinstance(level, int) and isinstance(names, list)):
            return None
        imports.append((module, level, tuple(str(name) for name in names)))
    return imports, [str(value) for value in raw_strings]


class _ScanCache:
    """Each Python file's scan, kept by size and modification time, under the git directory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = git_path(root, "py-qa/affected-cache.json")
        self.entries: dict[str, object] = {}
        if self.path is not None and self.path.is_file():
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                stored = None
            if isinstance(stored, dict) and stored.get("version") == _cache_version():
                files = stored.get("files")
                self.entries = files if isinstance(files, dict) else {}

    def scans(self, names: list[str]) -> dict[str, Scan]:
        """Return the scan of every named file, parsing only those changed since last cached."""
        found: dict[str, Scan] = {}
        stale: list[str] = []
        stamps: dict[str, list[int]] = {}
        for name in names:
            stat = (self.root / name).stat()
            stamps[name] = [stat.st_mtime_ns, stat.st_size]
            cached = _cached_scan(self.entries.get(name), stamps[name])
            if cached is None:
                stale.append(name)
            else:
                found[name] = cached
        paths = [str(self.root / name) for name in stale]
        if len(stale) >= PARALLEL_THRESHOLD:
            with ProcessPoolExecutor(max_workers=os.cpu_count()) as pool:
                results = list(pool.map(_scan_file, paths, chunksize=32))
        else:
            results = [_scan_file(path) for path in paths]
        found.update(zip(stale, results, strict=True))
        if stale and self.path is not None:
            files = {
                name: [stamps[name], [list(item) for item in scan[0]], scan[1]]
                for name, scan in found.items()
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": _cache_version(), "files": files}
            self.path.write_text(json.dumps(payload), encoding="utf-8")
        return found


def _all_files(root: Path) -> list[str]:
    if (root / ".git").exists():
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            capture_output=True,
            check=True,
        )
        return sorted(
            name for name in result.stdout.decode().split("\0") if name and (root / name).is_file()
        )
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not SKIPPED_DIRECTORIES.intersection(path.relative_to(root).parts)
    )


def _test_patterns(root: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return pytest's python_files patterns and its testpaths, as the project configures them."""
    options = read_pyproject(root).get("tool", {}).get("pytest", {}).get("ini_options", {})
    files = options.get("python_files", _DEFAULT_TEST_FILES)
    patterns = tuple(files.split()) if isinstance(files, str) else tuple(files)
    testpaths = options.get("testpaths", ())
    paths = tuple(testpaths.split()) if isinstance(testpaths, str) else tuple(testpaths)
    return patterns, tuple(path.strip("/") for path in paths)


class _Graph:
    """Every project file, the module names each Python file answers to, and their references."""

    def __init__(self, root: Path, files: list[str]) -> None:
        self.root = root
        self.files: set[str] = set()
        self.modules: dict[str, set[str]] = defaultdict(set)
        self.by_suffix: dict[str, set[str]] = defaultdict(set)
        self.by_name: dict[str, set[str]] = defaultdict(set)
        self.packages: dict[str, list[str]] = {}
        self._is_package: dict[PurePosixPath, bool] = {}
        for name in files:
            self.add(name)

    def add(self, name: str) -> None:
        """Index a file, present or gone from the tree, so references to it resolve."""
        if name in self.files:
            return
        self.files.add(name)
        parts = name.split("/")
        self.by_name[parts[-1]].add(name)
        for start in range(1, len(parts) - 1):
            self.by_suffix["/".join(parts[start:])].add(name)
        if not name.endswith(".py"):
            return
        path = PurePosixPath(name)
        package = self._package(path.parent)
        self.packages[name] = package
        stem = [] if path.name == "__init__.py" else [path.stem]
        for dotted in ([*path.parent.parts, *stem], [*package, *stem]):
            if dotted and all(part.isidentifier() for part in dotted):
                self.modules[".".join(dotted)].add(name)

    def _package(self, directory: PurePosixPath) -> list[str]:
        """Return the dotted package a directory is, as relative imports resolve it."""
        parts: list[str] = []
        while directory.parts:
            if directory not in self._is_package:
                self._is_package[directory] = (self.root / directory / "__init__.py").is_file()
            if not self._is_package[directory]:
                break
            parts.insert(0, directory.name)
            directory = directory.parent
        return parts

    def resolve_module(self, dotted: str, found: dict[str, int]) -> None:
        """Add the files importing dotted runs: the module itself, and its packages implicitly."""
        parts = dotted.split(".")
        for end in range(1, len(parts) + 1):
            kind = EXPLICIT if end == len(parts) else IMPLICIT
            for name in self.modules.get(".".join(parts[:end]), ()):
                _merge(found, name, kind)

    def resolve_string(self, text: str, found: dict[str, int]) -> None:
        """Add the project files a string names: as a module, a path, or a unique file name.

        A string holding spaces or lines, such as a message or an embedded script, is read word
        by word for paths and file names, and what it names is reached weakly: a test that names
        a file in a message is selected for it, but a module that does is not a way through.
        """
        if not any(character.isspace() for character in text):
            parts = text.split(".")
            for end in range(len(parts), 1, -1):
                if ".".join(parts[:end]) in self.modules:
                    self.resolve_module(".".join(parts[:end]), found)
                    break
            words, kind = [text], EXPLICIT
        else:
            words, kind = _PATH_WORD.findall(text), WEAK
        for word in words:
            for name in self._resolve_path(word.removeprefix("./").rstrip("/.")):
                _merge(found, name, kind)

    def _resolve_path(self, path: str) -> set[str]:
        if "/" in path:
            pieces = path.split("/")
            for start in range(len(pieces) - 1):
                candidate = "/".join(pieces[start:])
                if candidate in self.files:
                    return {candidate}
                if candidate in self.by_suffix:
                    return self.by_suffix[candidate]
            return set()
        if "." in path and len(self.by_name.get(path, ())) == 1:
            return self.by_name[path]
        return set()

    def references(self, name: str, scan: Scan) -> dict[str, int]:
        """Return the project files one Python file reaches, each marked explicit or implicit."""
        imports, strings = scan
        package = self.packages.get(name, [])
        found: dict[str, int] = {}
        for module, level, names in imports:
            if level:
                keep = len(package) - (level - 1)
                if keep < 0:
                    continue
                base = [*package[:keep], *(module.split(".") if module else [])]
            else:
                base = module.split(".") if module else []
            if base:
                self.resolve_module(".".join(base), found)
            for imported in names:
                self.resolve_module(".".join([*base, imported]), found)
        for text in strings:
            self.resolve_string(text, found)
        found.pop(name, None)
        return found


def _merge(found: dict[str, int], name: str, kind: int) -> None:
    found[name] = max(found.get(name, WEAK), kind)


def _is_test(name: str, patterns: tuple[str, ...], testpaths: tuple[str, ...]) -> bool:
    if not name.endswith(".py"):
        return False
    if testpaths and not any(name == path or name.startswith(path + "/") for path in testpaths):
        return False
    return any(fnmatch.fnmatchcase(PurePosixPath(name).name, pattern) for pattern in patterns)


def _conftests(name: str, files: set[str]) -> set[str]:
    found: set[str] = set()
    directory = PurePosixPath(name).parent
    while True:
        candidate = (directory / "conftest.py").as_posix().removeprefix("./")
        if candidate in files and candidate != name:
            found.add(candidate)
        if not directory.parts:
            return found
        directory = directory.parent


@dataclass
class Referrers:
    """For each file, the files that reach it, split by whether they name it or only its package."""

    explicit: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    implicit: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    weak: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    def reach(self, start: str) -> set[str]:
        """Return every file from which start is reachable.

        An implicit edge is followed only out of start itself: a change to a package's __init__
        or a conftest reaches every file that loads it, but what it imports does not.
        """
        seen = set(self.implicit.get(start, ()))
        pending = [start, *seen]
        while pending:
            for referrer in self.explicit.get(pending.pop(), ()):
                if referrer not in seen:
                    seen.add(referrer)
                    pending.append(referrer)
        seen.discard(start)
        return seen


def build_referrers(config: Config, deleted: tuple[str, ...] = ()) -> tuple[Referrers, set[str]]:
    """Return the reverse reference graph of the project, and its test files."""
    root = config.root
    graph = _Graph(root, _all_files(root))
    for name in deleted:
        graph.add(name)
    patterns, testpaths = _test_patterns(root)
    tests = {name for name in graph.files if _is_test(name, patterns, testpaths)} - set(deleted)
    present = sorted(name for name in graph.files if name.endswith(".py") and name not in deleted)
    scans = _ScanCache(root).scans(present)
    referrers = Referrers()
    for name in present:
        targets = graph.references(name, scans[name])
        if name in tests:
            for conftest in _conftests(name, graph.files):
                _merge(targets, conftest, IMPLICIT)
        kinds = {EXPLICIT: referrers.explicit, IMPLICIT: referrers.implicit, WEAK: referrers.weak}
        for target, kind in targets.items():
            kinds[kind][target].add(name)
    return referrers, tests


def _own_inputs(config: Config) -> tuple[DiffMapEntry, ...]:
    """Return the files py-qa's own lanes check, which no test needs to read to be covered."""
    why = "checked by py-qa's own lanes in every run"
    globs = ["/" + config.record.path, "/" + config.docs_dir.rstrip("/") + "/**"]
    if config.summary_file is not None:
        globs.append("/" + config.summary_file)
    return tuple(DiffMapEntry(glob, (), why) for glob in globs)


def select_tests(config: Config, change: Change) -> Selection:
    """Return the tests the change can affect, or a full run and the reason one is needed."""
    policy = config.diff
    referrers, tests = build_referrers(config, change.deleted)
    reached_by: dict[str, set[str]] = defaultdict(set)
    full_reasons: list[str] = []
    unmapped: list[str] = []
    untested: list[str] = []
    for name in sorted({*change.files, *change.deleted}):
        if match_any(policy.full_tests_on, name):
            full_reasons.append(f"{name}: listed in [tool.py-qa.diff] full_tests_on")
            continue
        mapped = [
            entry
            for entry in (*policy.map, *_own_inputs(config))
            if match_glob(entry.glob, name) and not match_any(entry.exclude, name)
        ]
        for entry in mapped:
            for test in entry.tests:
                reached_by[test].add(name)
        reached = referrers.reach(name)
        reached_tests = {
            node for node in reached | referrers.weak.get(name, set()) if node in tests
        }
        if name in tests:
            reached_tests.add(name)
        for test in reached_tests:
            reached_by[test].add(name)
        if reached_tests or mapped:
            continue
        if name.endswith(".py") or reached:
            untested.append(name)
        else:
            unmapped.append(name)
            if policy.unmapped == "full":
                full_reasons.append(f"{name}: no test is known to read it")
    declared = {test for entry in policy.map for test in entry.tests}
    root = config.root
    missing = tuple(sorted(test for test in declared if not (root / test.split("::")[0]).exists()))
    return Selection(
        full=bool(full_reasons),
        full_reasons=tuple(full_reasons),
        tests=tuple(sorted(test for test in reached_by if test not in missing)),
        reached_by={test: tuple(sorted(names)) for test, names in sorted(reached_by.items())},
        unmapped=tuple(unmapped),
        untested=tuple(untested),
        missing=missing,
    )


class SelectorError(Exception):
    """The project's diff selector failed or printed something that is not its selection."""


def capture(command: list[str], cwd: Path) -> tuple[int, str]:
    """Run a command without a shell and return its exit status and its standard output."""
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    except OSError as error:
        return 127, str(error)
    return result.returncode, result.stdout


def with_selector(
    config: Config,
    change: Change,
    selection: Selection,
    run: Callable[[list[str], Path], tuple[int, str]] = capture,
) -> Selection:
    """Return the selection widened by the project's own selector, when it has one.

    The selector's tests join the graph's; a file it cannot map is unmapped, as one the graph
    cannot reach is.
    """
    selector = config.diff.selector
    if selector is None:
        return selection
    tokens = {
        "{python}": sys.executable,
        "{base}": change.base,
        "{merge_base}": change.merge_base,
        "{range}": f"{change.merge_base}..HEAD",
    }
    command = [tokens.get(argument, argument) for argument in selector.command]
    code, output = run(command, config.root)
    if code != 0:
        msg = f"the diff selector exited {code}: {' '.join(command)}"
        raise SelectorError(msg)
    try:
        data = json.loads(output)
    except json.JSONDecodeError as error:
        msg = f"the diff selector printed no JSON: {error}"
        raise SelectorError(msg) from error
    tests = _string_list(data, selector.tests_key)
    unmapped = _string_list(data, selector.unmapped_key) if selector.unmapped_key else []
    reached_by = {test: set(names) for test, names in selection.reached_by.items()}
    for test in tests:
        reached_by.setdefault(test, set()).add("[tool.py-qa.diff.selector]")
    new_unmapped = [name for name in unmapped if name not in selection.unmapped]
    reasons = list(selection.full_reasons)
    if config.diff.unmapped == "full":
        reasons.extend(f"{name}: the diff selector cannot map it" for name in new_unmapped)
    root = config.root
    return Selection(
        full=bool(reasons),
        full_reasons=tuple(reasons),
        tests=tuple(sorted(test for test in reached_by if (root / test.split("::")[0]).exists())),
        reached_by={test: tuple(sorted(names)) for test, names in sorted(reached_by.items())},
        unmapped=(*selection.unmapped, *new_unmapped),
        untested=selection.untested,
        missing=selection.missing,
    )


def _string_list(data: object, key: str) -> list[str]:
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        msg = f"the diff selector's JSON has no list of strings under {key!r}"
        raise SelectorError(msg)
    return value
