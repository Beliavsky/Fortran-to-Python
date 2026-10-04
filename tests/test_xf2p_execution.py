"""Compile original Fortran and compare it with independently executed Python."""
from __future__ import annotations

import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
CASES = Path(__file__).parent / "cases"
NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?$")
KNOWN_FAILURES = {
    "formatted_file_io": "numeric file unit produces invalid Python 20.close()",
    "execute_command_line": "EXECUTE_COMMAND_LINE has no translated helper",
    "selected_integer_kind": "SELECTED_INT_KIND has no translated helper",
    "selected_logical_kind": "SELECTED_LOGICAL_KIND has no translated helper",
    "selected_real_kind": "SELECTED_REAL_KIND has no translated helper",
    "type_extension": "parent component of an extended type is missing",
}


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=90)


def require_success(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, f"{result.args}\n{result.stdout}\n{result.stderr}"


def compare_output(reference: str, actual: str) -> None:
    """Ignore whitespace, not labels, token counts, or integer differences."""
    expected_tokens, actual_tokens = reference.split(), actual.split()
    assert len(expected_tokens) == len(actual_tokens), (reference, actual)
    for index, (expected, observed) in enumerate(zip(expected_tokens, actual_tokens)):
        if NUMBER.fullmatch(expected) and NUMBER.fullmatch(observed):
            if re.fullmatch(r"[+-]?\d+", expected) and re.fullmatch(r"[+-]?\d+", observed):
                assert int(expected) == int(observed), (index, expected, observed)
            else:
                assert math.isclose(float(expected.replace("D", "e").replace("d", "e")),
                                    float(observed.replace("D", "e").replace("d", "e")),
                                    rel_tol=1e-9, abs_tol=1e-11), (index, expected, observed)
        else:
            assert expected == observed, (index, expected, observed)


@pytest.mark.parametrize("source", sorted(p for p in CASES.rglob("*.f90")
                                         if "stash" not in p.relative_to(CASES).parts),
                         ids=lambda p: p.stem)
def test_fortran_and_translated_python_agree(source: Path, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for execution comparisons")
    pytest.importorskip("numpy")
    if source.stem == "math_intrinsics":
        pytest.importorskip("scipy", reason="special-function translations require SciPy")
    reference_dir = tmp_path / "fortran"
    translated_dir = tmp_path / "python"
    reference_dir.mkdir()
    translated_dir.mkdir()
    exe = tmp_path / ("reference.exe" if os.name == "nt" else "reference")
    # This MinGW toolchain lowers array SINPI to an unavailable libm symbol
    # at -O0; -O3 constant-folds the fixed Fortran 2023 reference vectors.
    optimization = "-O3" if source.stem == "math_intrinsics" else "-O0"
    require_success(run([compiler, optimization, "-g", "-fcheck=all", "-fbacktrace",
                         str(source), "-o", str(exe)], tmp_path))
    original = run([str(exe)], reference_dir)
    require_success(original)
    # For round-trip cases, independently check the original Python as well.
    python_source = source.with_suffix(".py")
    if python_source.exists():
        python_dir = tmp_path / "original_python"
        python_dir.mkdir()
        python_original = run([sys.executable, str(python_source)], python_dir)
        require_success(python_original)
        compare_output(original.stdout, python_original.stdout)
    # Mark only after validating the independent reference. Strict XPASS forces
    # removal of obsolete expectations when the translator improves.
    if source.stem in KNOWN_FAILURES:
        request.node.add_marker(pytest.mark.xfail(
            reason=KNOWN_FAILURES[source.stem], strict=True, raises=AssertionError))
    output = translated_dir / "translated.py"
    translated = run([sys.executable, str(ROOT / "xf2p.py"), str(source),
                      "--out", str(output)], tmp_path)
    require_success(translated)
    assert output.exists(), translated.stdout
    executed = run([sys.executable, str(output)], translated_dir)
    require_success(executed)
    compare_output(original.stdout, executed.stdout)


def test_output_comparison_rejects_integer_off_by_one() -> None:
    with pytest.raises(AssertionError):
        compare_output("iterations 19", "iterations 18")


def test_output_comparison_tolerates_float_roundoff() -> None:
    compare_output("value 1.0000000000D+00", "value 1.0000000001")


def test_output_comparison_rejects_missing_output() -> None:
    with pytest.raises(AssertionError):
        compare_output("1 2", "1")
