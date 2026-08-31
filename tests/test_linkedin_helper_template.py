from __future__ import annotations

import ast
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).parent.parent / "scripts" / "onboarding" / "linkedin_helper.py.tmpl"


def test_template_is_valid_python_after_substitution():
    template = _TEMPLATE_PATH.read_text()
    filled = template.replace("{{BASE_URL}}", "http://localhost:5000").replace("{{TOKEN}}", "abc123")

    ast.parse(filled)  # raises SyntaxError if the substituted script is broken


def test_template_has_no_leftover_placeholders_after_substitution():
    template = _TEMPLATE_PATH.read_text()
    filled = template.replace("{{BASE_URL}}", "http://localhost:5000").replace("{{TOKEN}}", "abc123")

    assert "{{" not in filled
