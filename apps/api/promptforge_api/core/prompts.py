"""Typed prompt templates.

Sits between a stored PromptVersion (body + a variables jsonb blob) and an actual
LLM call. Declares variables, checks them against the `{{name}}` placeholders in
the body, renders with all errors collected at once, and fingerprints the
(body, variables) pair for cheap version comparison.

Validation is applicative rather than fail-fast: render() gathers every problem
and raises a single PromptValidationError listing all of them, so a caller filling
a form sees all their mistakes in one round-trip instead of one at a time.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

VariableType = Literal["str", "int", "float", "bool"]

_VAR_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class PromptValidationError(Exception):
    """Raised by render() when inputs don't satisfy the template. Holds every error."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class PromptVariable(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z_]\w*$")
    type: VariableType = "str"
    required: bool = True
    default: Any = None
    choices: list[Any] | None = None
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    description: str | None = None

    @property
    def has_default(self) -> bool:
        return self.default is not None


class PromptTemplate(BaseModel):
    body: str
    variables: list[PromptVariable] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        names = [v.name for v in self.variables]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"duplicate variable declarations: {dupes}")

        undeclared = sorted(self.referenced_names - set(names))
        if undeclared:
            raise ValueError(f"body references undeclared variables: {undeclared}")
        return self

    @property
    def referenced_names(self) -> set[str]:
        return set(_VAR_PATTERN.findall(self.body))

    def render(self, **values: Any) -> str:
        declared = {v.name: v for v in self.variables}
        errors: list[str] = []

        for key in values:
            if key not in declared:
                errors.append(f"unexpected variable: {key!r}")

        resolved: dict[str, Any] = {}
        for var in self.variables:
            if var.name in values:
                value = values[var.name]
            elif var.has_default:
                value = var.default
            else:
                if var.required:
                    errors.append(f"missing required variable: {var.name!r}")
                continue
            type_error = _validate_value(var, value)
            if type_error:
                errors.append(type_error)
                continue
            resolved[var.name] = value

        # A placeholder in the body must end up with a concrete value, even if its
        # variable was declared optional.
        for name in sorted(self.referenced_names):
            if name not in resolved and not any(name in e for e in errors):
                errors.append(f"variable {name!r} is referenced in body but has no value")

        if errors:
            raise PromptValidationError(sorted(set(errors)))

        return _VAR_PATTERN.sub(lambda m: str(resolved[m.group(1)]), self.body)

    def fingerprint(self) -> str:
        """Stable SHA-256 over (body, variables). Order-independent on variables."""
        payload = {
            "body": self.body,
            "variables": sorted(
                (v.model_dump() for v in self.variables),
                key=lambda d: d["name"],
            ),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()


def _validate_value(var: PromptVariable, value: Any) -> str | None:
    # bool is a subclass of int, so the int/float branches reject it explicitly.
    if var.type == "str" and not isinstance(value, str):
        return f"{var.name!r} expected str, got {type(value).__name__}"
    if var.type == "bool" and not isinstance(value, bool):
        return f"{var.name!r} expected bool, got {type(value).__name__}"
    if var.type == "int" and (not isinstance(value, int) or isinstance(value, bool)):
        return f"{var.name!r} expected int, got {type(value).__name__}"
    if var.type == "float" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        return f"{var.name!r} expected float, got {type(value).__name__}"

    if var.choices is not None and value not in var.choices:
        return f"{var.name!r} must be one of {var.choices}, got {value!r}"

    if var.type == "str" and isinstance(value, str):
        if var.min_length is not None and len(value) < var.min_length:
            return f"{var.name!r} is shorter than min_length {var.min_length}"
        if var.max_length is not None and len(value) > var.max_length:
            return f"{var.name!r} is longer than max_length {var.max_length}"
    return None
