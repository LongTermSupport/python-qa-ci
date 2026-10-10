# Changelog

Every release of py-qa-ci, newest first. Versions follow semantic versioning; whilst the major
version is 0, a minor release can break a consuming project, and says how.

## 0.2.0

### Renamed: python-qa-ci is now py-qa-ci

Every name the tool carried is changed. A project upgrading from 0.1.0 changes these:

| What                         | 0.1.0                                                  | 0.2.0                                              |
| ---------------------------- | ------------------------------------------------------ | -------------------------------------------------- |
| Repository                   | `LongTermSupport/python-qa-ci`                         | `LongTermSupport/py-qa-ci`                         |
| Distribution                 | `python-qa-ci`                                         | `py-qa-ci`                                         |
| Command                      | `python-qa`                                            | `py-qa`                                            |
| Import package               | `python_qa`                                            | `py_qa`                                            |
| Bundled Pylint plugin module | `python_qa.pylint_plugin`                              | `py_qa.pylint_plugin`                              |
| Configuration table          | `[tool.python-qa]` and its sub-tables                  | `[tool.py-qa]` and its sub-tables                  |
| Agent summary markers        | `<!-- BEGIN python-qa summary ... -->`, `<!-- END ...` | `<!-- BEGIN py-qa summary ... -->`, `<!-- END ...` |

- **Rule identifiers are unchanged.** They already used the short prefix `pyqaci`, which reads as
  py-qa-ci: `pyqaci.*` for py-qa's own detectors, `pyqaci-sensitive-repr` (W9701) and
  `pyqaci-broad-suppress` (W9702) for the bundled Pylint messages, and the Pylint options
  `--pyqaci-sensitive-names` and `--pyqaci-redacting-types`. Project records, documentation
  pages and anything else that names an identifier need no change.
- **A `[tool.python-qa]` table is now a configuration error** (exit 2), naming the new table.
  Ignoring it would have run every lane on the defaults, without the project's record path,
  plugins or switches.
- **An agent summary region under the former markers** is replaced in place by the next
  `py-qa summary`; until then the `summary` lane reports it stale, as it does after any upgrade.
- GitHub redirects the former repository URL, but a pinned install line should name the new
  one: `py-qa-ci @ git+https://github.com/LongTermSupport/py-qa-ci@v0.2.0`.

## 0.1.0

The first release, as `python-qa-ci`: the `run` pipeline (format, detectors, runners), the
project record, the suppression scan, the bundled Pylint defences `pyqaci-sensitive-repr` and
`pyqaci-broad-suppress`, offline `rule-doc`, `rules`, `docs-check` and the agent summary.
