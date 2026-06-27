import io
import unittest
from unittest.mock import MagicMock, patch

from tools import quality


class TestQualityTool(unittest.TestCase):
    def test_check_runs_expected_blocking_steps_in_order(self):
        names = [step.name for step in quality.CHECK_STEPS]
        self.assertEqual(
            names,
            [
                "ruff check",
                "ruff format --check",
                "ty check",
                "unittest",
                "coverage run",
                "coverage report",
                "bandit",
                "detect-secrets baseline",
                "detect-secrets report",
                "interrogate",
                "vulture",
                "xenon complexity",
            ],
        )

    def test_generic_tool_gates_are_registered(self):
        for gate in ("security", "docs", "dead-code", "complexity", "metrics", "wily", "pre-commit"):
            self.assertIn(gate, quality.COMMANDS)

    def test_run_steps_stops_on_first_failure(self):
        runner = MagicMock()
        runner.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=3),
            MagicMock(returncode=0),
        ]

        with patch("sys.stdout", new_callable=io.StringIO):
            result = quality.run_steps(
                [
                    quality.Step("one", ("cmd", "one")),
                    quality.Step("two", ("cmd", "two")),
                    quality.Step("three", ("cmd", "three")),
                ],
                runner=runner,
            )

        self.assertEqual(result, 3)
        self.assertEqual(runner.call_count, 2)

    def test_single_gate_uses_named_command(self):
        runner = MagicMock(return_value=MagicMock(returncode=0))

        with patch("sys.stdout", new_callable=io.StringIO):
            result = quality.run_steps(quality.COMMANDS["typecheck"], runner=runner)

        self.assertEqual(result, 0)
        runner.assert_called_once_with(("uv", "run", "ty", "check"), check=False)

    def test_tracked_path_gate_appends_git_tracked_files(self):
        runner = MagicMock()
        runner.side_effect = [
            MagicMock(returncode=0, stdout="xpwebapi/ws.py\ntests/test_ws.py\n"),
            MagicMock(returncode=0),
        ]

        with patch("sys.stdout", new_callable=io.StringIO):
            result = quality.run_steps(
                [
                    quality.Step(
                        "tracked",
                        ("uv", "run", "detect-secrets-hook", "--baseline", ".secrets.baseline"),
                        tracked_paths=("xpwebapi", "tests"),
                    )
                ],
                runner=runner,
            )

        self.assertEqual(result, 0)
        runner.assert_any_call(("git", "ls-files", "--", "xpwebapi", "tests"), check=False, capture_output=True, text=True)
        runner.assert_any_call(
            (
                "uv",
                "run",
                "detect-secrets-hook",
                "--baseline",
                ".secrets.baseline",
                "xpwebapi/ws.py",
                "tests/test_ws.py",
            ),
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
