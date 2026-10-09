# pyqaci-sensitive-repr

Pylint message `W9701`, bundled with python-qa and on in every project.

## What it flags

An annotated field whose name marks it as a credential, in a class whose `__repr__` is
generated:

- a class decorated with `dataclasses.dataclass` or `pydantic.dataclasses.dataclass`, through any
  import spelling (`@dataclass`, `@dc.dataclass(frozen=True)`), unless the decorator passes
  `repr=False`;
- a subclass of `pydantic.BaseModel`, resolved through its ancestors (pydantic must be importable
  where Pylint runs). Fields whose names start with an underscore are private attributes and
  are not printed, so they are skipped.

A name is sensitive when one of its words is in the list, or a run of its words matches an
entry with an underscore. Words are split at underscores and at lower-to-upper case changes, so
`apiKey` is `api key`. The default list: `password`, `passwd`, `passphrase`, `secret`, `token`,
`credential`, `credentials`, `apikey`, `api_key`, `private_key`, `access_key`, `secret_key`.
`refresh_token` matches; `max_tokens`, `tokenizer` and `secretary` do not.

Not flagged: a field declared with `repr=False` (`field(repr=False)`, `Field(repr=False)`), a
field whose annotation names a redacting type (default `SecretStr`, `SecretBytes`, `Secret`,
anywhere in the annotation, so `SecretStr | None` qualifies), a `ClassVar`, and any class that
writes `__repr__` itself.

## Why

A generated `__repr__` prints every field verbatim. The repr reaches log lines (`%r`, `{obj!r}`),
tracebacks with local variables, assertion messages and debugger output, so a credential held
in a plain field leaks the first time the object is logged, usually by code written long after
the field was added.

## How to fix correctly

Keep the field out of the repr, and keep the name: the name is what tells readers it is
sensitive.

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Login:
    user: str
    password: str = field(repr=False)
```

With pydantic, hold the value in a redacting type, which also keeps it out of serialised
output unless asked for:

```python
from pydantic import BaseModel, SecretStr


class Settings(BaseModel):
    api_key: SecretStr
```

Writing `__repr__` by hand, and redacting the field in it, is the third correct form.

## Configuration

In `[tool.python-qa.sensitive_repr]`: `names` replaces the name list and `redacting_types`
replaces the redacting types (simple names). Both replace their defaults rather than extending
them; copy the defaults in to keep them.

## Suppression

Only with `pylint: disable=pyqaci-sensitive-repr` on the line, naming the message, together
with a `pylint::pyqaci-sensitive-repr` exception for that file in the project record. Anything
else fails `pyqaci.suppression.unrecorded` or `pyqaci.suppression.blanket`.
