"""Documentation and example contract tests."""

from __future__ import annotations

import ast
from pathlib import Path
import tomllib
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"
DOCS_DIR = REPO_ROOT / "docs"


class TestExampleAnnotations(unittest.TestCase):
    def test_examples_have_function_annotations(self) -> None:
        missing: list[str] = []

        for path in sorted(EXAMPLES_DIR.glob("*.py")):
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(module):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    if node.returns is None:
                        missing.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} {node.name} missing return annotation")

                    arguments = [
                        *node.args.posonlyargs,
                        *node.args.args,
                        *node.args.kwonlyargs,
                    ]
                    if node.args.vararg is not None:
                        arguments.append(node.args.vararg)
                    if node.args.kwarg is not None:
                        arguments.append(node.args.kwarg)

                    for argument in arguments:
                        if argument.arg in {"self", "cls"}:
                            continue
                        if argument.annotation is None:
                            missing.append(f"{path.relative_to(REPO_ROOT)}:{argument.lineno} {node.name}.{argument.arg} missing parameter annotation")

        self.assertEqual([], missing)


class TestDocumentationContent(unittest.TestCase):
    def test_readme_development_install_matches_project_metadata(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        dev_extra = pyproject.get("project", {}).get("optional-dependencies", {}).get("dev")

        if dev_extra is None:
            self.assertNotIn("xpwebapi[dev]", readme)
            self.assertIn("uv sync", readme)
        else:
            self.assertIn("xpwebapi[dev]", readme)

    def test_usage_docs_include_required_patterns(self) -> None:
        usage = (DOCS_DIR / "usage" / "index.md").read_text(encoding="utf-8")

        for heading in ["Connection lifecycle", "Monitoring datarefs", "Executing commands"]:
            with self.subTest(heading=heading):
                self.assertIn(f"## {heading}", usage)

    def test_reference_docs_use_valid_mkdocstrings_directives(self) -> None:
        reference_pages = sorted((DOCS_DIR / "reference").glob("*.md"))
        directives: dict[str, list[str]] = {}

        for path in reference_pages:
            lines = path.read_text(encoding="utf-8").splitlines()
            directives[path.name] = [line.strip() for line in lines if line.strip().startswith(":::")]

        self.assertIn("package.md", directives)
        self.assertIn("rest.md", directives)
        self.assertIn("websocket.md", directives)
        self.assertIn("udp.md", directives)
        self.assertNotIn("# :::", (DOCS_DIR / "reference" / "index.md").read_text(encoding="utf-8"))
        self.assertTrue(any("::: xpwebapi" == directive for directive in directives["package.md"]))
        self.assertTrue(any("::: xpwebapi.rest" == directive for directive in directives["rest.md"]))
        self.assertTrue(any("::: xpwebapi.ws" == directive for directive in directives["websocket.md"]))
        self.assertTrue(any("::: xpwebapi.udp" == directive for directive in directives["udp.md"]))

    def test_mkdocs_navigation_publishes_reference_pages(self) -> None:
        mkdocs = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")

        for nav_entry in [
            "Package: reference/package.md",
            "REST: reference/rest.md",
            "Async REST: reference/async-rest.md",
            "WebSocket: reference/websocket.md",
            "UDP: reference/udp.md",
            "Beacon: reference/beacon.md",
        ]:
            with self.subTest(nav_entry=nav_entry):
                self.assertIn(nav_entry, mkdocs)


if __name__ == "__main__":
    unittest.main()
