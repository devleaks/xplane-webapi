"""Repo-local quality gate runner."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

SOURCE_PATHS = ("xpwebapi", "tests", "tools")
PYTHON_QUALITY_PATHS = SOURCE_PATHS
SECRET_SCAN_PATHS = (".",)
SECRET_BASELINE = ".secrets.baseline"
COVERAGE_MINIMUM = "40"
XENON_MAX_ABSOLUTE = "C"
XENON_MAX_MODULES = "B"
XENON_MAX_AVERAGE = "A"


@dataclass(frozen=True)
class Step:
    name: str
    command: tuple[str, ...]
    tracked_paths: tuple[str, ...] = ()


def uv(*args: str) -> tuple[str, ...]:
    return ("uv", "run", *args)


COMMANDS: dict[str, tuple[Step, ...]] = {
    "lint": (Step("ruff check", uv("ruff", "check", *SOURCE_PATHS)),),
    "format-check": (Step("ruff format --check", uv("ruff", "format", "--check", *SOURCE_PATHS)),),
    "format": (Step("ruff format", uv("ruff", "format", *SOURCE_PATHS)),),
    "typecheck": (Step("ty check", uv("ty", "check")),),
    "test": (Step("unittest", uv("python", "-m", "unittest", "discover", "-v")),),
    "coverage": (
        Step("coverage run", uv("coverage", "run", "-m", "unittest", "discover", "-s", "tests", "-t", ".")),
        Step("coverage report", uv("coverage", "report", f"--fail-under={COVERAGE_MINIMUM}")),
    ),
    "security": (
        Step("bandit", uv("bandit", "-q", "-r", "xpwebapi")),
        Step("detect-secrets baseline", uv("detect-secrets-hook", "--baseline", SECRET_BASELINE), tracked_paths=SECRET_SCAN_PATHS),
        Step("detect-secrets report", uv("detect-secrets", "audit", "--report", SECRET_BASELINE)),
    ),
    "docs": (Step("interrogate", uv("interrogate", "-v", "-f", "40", "xpwebapi")),),
    "dead-code": (Step("vulture", uv("vulture", *PYTHON_QUALITY_PATHS, "--min-confidence", "80")),),
    "metrics": (
        Step("lizard report", uv("lizard", "xpwebapi", "-i", "-1")),
        Step("cohesion report", uv("cohesion", "-d", "xpwebapi")),
    ),
    "wily": (
        Step("wily build", uv("wily", "build", "xpwebapi")),
        Step("wily report", uv("wily", "report", "xpwebapi")),
    ),
    "complexity": (
        Step(
            "xenon complexity",
            uv(
                "xenon",
                "--max-absolute",
                XENON_MAX_ABSOLUTE,
                "--max-modules",
                XENON_MAX_MODULES,
                "--max-average",
                XENON_MAX_AVERAGE,
                "xpwebapi",
            ),
        ),
    ),
    "pre-commit": (Step("pre-commit", uv("pre-commit", "run", "--all-files")),),
}

CHECK_STEPS = (
    *COMMANDS["lint"],
    *COMMANDS["format-check"],
    *COMMANDS["typecheck"],
    *COMMANDS["test"],
    *COMMANDS["coverage"],
    *COMMANDS["security"],
    *COMMANDS["docs"],
    *COMMANDS["dead-code"],
    *COMMANDS["complexity"],
)


def run_steps(steps: Sequence[Step], runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> int:
    for step in steps:
        command = step.command
        if step.tracked_paths:
            tracked = runner(("git", "ls-files", "--", *step.tracked_paths), check=False, capture_output=True, text=True)
            if tracked.returncode != 0:
                return tracked.returncode
            command = (*command, *(line for line in tracked.stdout.splitlines() if line))

        print(f"==> {step.name}: {' '.join(command)}", flush=True)
        result = runner(command, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run xplane-webapi quality gates.")
    parser.add_argument(
        "gate",
        choices=(*COMMANDS.keys(), "check"),
        help="Quality gate to run. Use 'check' for the full blocking suite.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    steps = CHECK_STEPS if args.gate == "check" else COMMANDS[args.gate]
    return run_steps(steps)


if __name__ == "__main__":
    raise SystemExit(main())
