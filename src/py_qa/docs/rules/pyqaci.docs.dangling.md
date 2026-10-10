# pyqaci.docs.dangling

Reported by the `docs` lane, and by `py-qa docs-check`.

## What it flags

A defence listed by `py-qa rules` that comes from the project's own Pylint plugins (or from
py-qa itself) and has no page, or a page without the three sections `## What it flags`,
`## Why` and `## How to fix correctly`. A project's pages live in `docs_dir` (default
`docs/defences`), one per identifier, named `<identifier>.md`.

Identifiers listed from Pylint's, Ruff's and mypy's own catalogues are not checked: they are
listed from the catalogue `py-qa rule-doc` reads, so they resolve by construction.

## Why

A rule that blocks without explaining leaves the person who meets it to guess what is wrong and
how to put it right, and the guess is usually a suppression. The identifier printed with a
finding has to lead somewhere, on disk, at the installed version.

## How to fix correctly

Write the page beside the others, saying what the rule flags, why that is a hazard, and the
correct construction with an example, not only what is forbidden:

```markdown
# proj-no-eval

## What it flags

Calls to the builtin eval.

## Why

eval runs whatever text it is given, so input that reaches it becomes code.

## How to fix correctly

Parse the input with ast.literal_eval, or json.loads for JSON.
```
