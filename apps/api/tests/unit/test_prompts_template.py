"""Unit tests for promptforge_api.core.prompts."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from promptforge_api.core.prompts import (
    PromptTemplate,
    PromptValidationError,
    PromptVariable,
)

# --- template construction / consistency ---------------------------------------------


def test_body_with_no_variables_is_valid() -> None:
    tmpl = PromptTemplate(body="hello world")
    assert tmpl.referenced_names == set()
    assert tmpl.render() == "hello world"


def test_referenced_but_undeclared_variable_rejected() -> None:
    with pytest.raises(ValidationError, match="undeclared variables"):
        PromptTemplate(body="hi {{name}}", variables=[])


def test_duplicate_variable_declarations_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate variable"):
        PromptTemplate(
            body="{{x}}",
            variables=[PromptVariable(name="x"), PromptVariable(name="x")],
        )


def test_declared_but_unreferenced_variable_is_allowed() -> None:
    tmpl = PromptTemplate(
        body="static text",
        variables=[PromptVariable(name="meta", required=False)],
    )
    assert tmpl.render() == "static text"


def test_variable_name_must_be_identifier() -> None:
    with pytest.raises(ValidationError):
        PromptVariable(name="1bad")


# --- rendering happy paths -----------------------------------------------------------


def test_render_substitutes_value() -> None:
    tmpl = PromptTemplate(
        body="Hello {{name}}!",
        variables=[PromptVariable(name="name")],
    )
    assert tmpl.render(name="Shawn") == "Hello Shawn!"


def test_render_handles_whitespace_in_placeholder() -> None:
    tmpl = PromptTemplate(
        body="Hello {{ name }}!",
        variables=[PromptVariable(name="name")],
    )
    assert tmpl.render(name="Shawn") == "Hello Shawn!"


def test_render_uses_default_when_value_absent() -> None:
    tmpl = PromptTemplate(
        body="n={{n}}",
        variables=[PromptVariable(name="n", type="int", required=False, default=3)],
    )
    assert tmpl.render() == "n=3"


def test_render_coerces_non_string_to_str_in_output() -> None:
    tmpl = PromptTemplate(
        body="count={{n}}",
        variables=[PromptVariable(name="n", type="int")],
    )
    assert tmpl.render(n=42) == "count=42"


# --- rendering errors (aggregated) ---------------------------------------------------


def test_render_missing_required_raises() -> None:
    tmpl = PromptTemplate(body="{{a}}", variables=[PromptVariable(name="a")])
    with pytest.raises(PromptValidationError) as exc:
        tmpl.render()
    assert any("missing required" in e for e in exc.value.errors)


def test_render_unexpected_variable_raises() -> None:
    tmpl = PromptTemplate(body="hi", variables=[])
    with pytest.raises(PromptValidationError) as exc:
        tmpl.render(extra="x")
    assert any("unexpected variable" in e for e in exc.value.errors)


def test_render_aggregates_multiple_errors() -> None:
    tmpl = PromptTemplate(
        body="{{a}} {{b}}",
        variables=[PromptVariable(name="a"), PromptVariable(name="b", type="int")],
    )
    with pytest.raises(PromptValidationError) as exc:
        tmpl.render(b="not-an-int", extra="y")
    # missing a, wrong type b, unexpected extra → 3 distinct errors
    assert len(exc.value.errors) == 3


def test_render_optional_referenced_but_not_provided_raises() -> None:
    tmpl = PromptTemplate(
        body="{{opt}}",
        variables=[PromptVariable(name="opt", required=False)],
    )
    with pytest.raises(PromptValidationError) as exc:
        tmpl.render()
    assert any("referenced in body" in e for e in exc.value.errors)


@pytest.mark.parametrize(
    ("vtype", "bad_value"),
    [
        ("str", 123),
        ("int", "x"),
        ("int", True),  # bool is not int here
        ("float", "x"),
        ("float", True),
        ("bool", 1),  # int is not bool
    ],
)
def test_render_type_mismatch(vtype: str, bad_value: object) -> None:
    tmpl = PromptTemplate(
        body="{{v}}",
        variables=[PromptVariable(name="v", type=vtype)],  # type: ignore[arg-type]
    )
    with pytest.raises(PromptValidationError) as exc:
        tmpl.render(v=bad_value)
    assert any("expected" in e for e in exc.value.errors)


def test_render_float_accepts_int() -> None:
    tmpl = PromptTemplate(body="{{v}}", variables=[PromptVariable(name="v", type="float")])
    assert tmpl.render(v=3) == "3"


def test_render_choices_violation() -> None:
    tmpl = PromptTemplate(
        body="{{tone}}",
        variables=[PromptVariable(name="tone", choices=["formal", "casual"])],
    )
    with pytest.raises(PromptValidationError) as exc:
        tmpl.render(tone="snarky")
    assert any("must be one of" in e for e in exc.value.errors)


def test_render_min_max_length() -> None:
    tmpl = PromptTemplate(
        body="{{s}}",
        variables=[PromptVariable(name="s", min_length=2, max_length=4)],
    )
    assert tmpl.render(s="abc") == "abc"
    with pytest.raises(PromptValidationError):
        tmpl.render(s="a")
    with pytest.raises(PromptValidationError):
        tmpl.render(s="abcde")


# --- fingerprint ---------------------------------------------------------------------


def test_fingerprint_stable_across_variable_order() -> None:
    a = PromptTemplate(
        body="{{x}}{{y}}",
        variables=[PromptVariable(name="x"), PromptVariable(name="y")],
    )
    b = PromptTemplate(
        body="{{x}}{{y}}",
        variables=[PromptVariable(name="y"), PromptVariable(name="x")],
    )
    assert a.fingerprint() == b.fingerprint()


def test_fingerprint_changes_with_body() -> None:
    a = PromptTemplate(body="a")
    b = PromptTemplate(body="b")
    assert a.fingerprint() != b.fingerprint()


def test_fingerprint_changes_with_variable_constraints() -> None:
    a = PromptTemplate(body="{{x}}", variables=[PromptVariable(name="x")])
    b = PromptTemplate(body="{{x}}", variables=[PromptVariable(name="x", max_length=10)])
    assert a.fingerprint() != b.fingerprint()


# --- property tests ------------------------------------------------------------------


@given(st.text(alphabet=st.characters(blacklist_characters="{}"), max_size=200))
def test_render_is_identity_when_no_variables(text: str) -> None:
    assert PromptTemplate(body=text).render() == text


@given(st.text(min_size=1, max_size=50))
def test_render_round_trip_single_string_var(value: str) -> None:
    tmpl = PromptTemplate(body="<{{v}}>", variables=[PromptVariable(name="v")])
    assert tmpl.render(v=value) == f"<{value}>"
