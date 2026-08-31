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


def test_template_handles_errors_without_raw_traceback():
    """The script should catch realistic failure modes and print a friendly
    message instead of letting an uncaught exception dump a traceback on a
    non-technical user."""
    template = _TEMPLATE_PATH.read_text()
    filled = template.replace("{{BASE_URL}}", "http://localhost:5000").replace("{{TOKEN}}", "abc123")

    tree = ast.parse(filled)

    # Find the try/except wrapping the main() call.
    try_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Try)]
    assert try_nodes, "expected a top-level try/except around main()"

    handler_types = set()
    for try_node in try_nodes:
        for handler in try_node.handlers:
            if handler.type is None:
                continue
            names = (
                [elt.id if isinstance(elt, ast.Name) else ast.unparse(elt) for elt in handler.type.elts]
                if isinstance(handler.type, ast.Tuple)
                else [handler.type.id if isinstance(handler.type, ast.Name) else ast.unparse(handler.type)]
            )
            handler_types.update(names)

    assert any(name.endswith("HTTPError") for name in handler_types)
    assert any(name.endswith("URLError") for name in handler_types)
    assert any(name.endswith("PlaywrightTimeoutError") for name in handler_types)
    assert "Exception" in handler_types

    # The specific handlers must come before the catch-all Exception handler.
    for try_node in try_nodes:
        if any(
            (h.type is not None and getattr(h.type, "id", None) == "Exception") for h in try_node.handlers
        ):
            exception_index = next(
                i for i, h in enumerate(try_node.handlers) if getattr(h.type, "id", None) == "Exception"
            )
            assert exception_index == len(try_node.handlers) - 1, "Exception handler must be last"
