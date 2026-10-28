import ast
import os
from pathlib import Path

FORBIDDEN_IMPORTS = {
    "fastapi",
    "starlette",
    "sqlalchemy",
    "aiosqlite",
    "asyncio",
    "httpx",
    "app.infrastructure",
    "app.api",
    "app.application",
}


def test_domain_is_pure():
    """Verifies that app.domain contains zero dependencies on external frameworks or infrastructure."""
    domain_dir = Path(__file__).resolve().parent.parent / "app" / "domain"
    assert domain_dir.exists(), f"Domain directory {domain_dir} does not exist"

    violations = []

    for py_file in domain_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    for forbidden in FORBIDDEN_IMPORTS:
                        if name == forbidden or name.startswith(forbidden + "."):
                            violations.append(f"{py_file.name}: imports {name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for forbidden in FORBIDDEN_IMPORTS:
                    if module == forbidden or module.startswith(forbidden + "."):
                        violations.append(f"{py_file.name}: imports from {module}")

    assert not violations, f"Architecture isolation violated in app/domain:\n" + "\n".join(violations)
