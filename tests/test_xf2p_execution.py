"""Compile original Fortran and compare it with independently executed Python."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from fortran_output_compare import compare_outputs

ROOT = Path(__file__).resolve().parents[1]
CASES = Path(__file__).parent / "cases"
KNOWN_FAILURES = {
    "execute_command_line": "EXECUTE_COMMAND_LINE has no translated helper",
    "type_extension": "parent component of an extended type is missing",
}


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=90)


def require_success(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, f"{result.args}\n{result.stdout}\n{result.stderr}"


def compare_output(reference: str, actual: str) -> None:
    """Ignore whitespace, not labels, token counts, or integer differences."""
    result = compare_outputs(reference, actual)
    assert result['status'] == 'match', (result, reference, actual)


def execution_sources(cases: Path, include_exploratory: bool = False) -> list[Path]:
    """Discover normal cases, optionally including the local survey directory."""
    return sorted(
        p for p in cases.rglob("*.f90")
        if "stash" not in p.relative_to(cases).parts
        and (include_exploratory or "more" not in p.relative_to(cases).parts)
    )


def pytest_generate_tests(metafunc):
    if metafunc.function.__name__ == "test_fortran_and_translated_python_agree":
        metafunc.parametrize(
            "source",
            execution_sources(CASES, metafunc.config.getoption("--include-exploratory")),
            ids=lambda p: p.stem,
        )


def test_fortran_and_translated_python_agree(source: Path, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for execution comparisons")
    pytest.importorskip("numpy")
    if source.stem in {"math_intrinsics", "modern_math_intrinsics"}:
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


@pytest.mark.parametrize("reference,actual", [
    ("T F", "True False"), ("True False", "T F"),
    ("flags T True F False", "flags True T False F"),
])
def test_output_comparison_accepts_logical_spellings(reference, actual) -> None:
    compare_output(reference, actual)


@pytest.mark.parametrize("reference,actual", [
    ("T", "False"), ("F", "True"), ("T", "1"), ("F", "0"),
    ("True", "1"), ("False", "0"), ("flag=T", "flag=True"),
    ("label", "different"),
])
def test_output_comparison_rejects_other_differences(reference, actual) -> None:
    with pytest.raises(AssertionError):
        compare_output(reference, actual)


@pytest.mark.parametrize("include_exploratory", [False, True])
def test_execution_source_discovery(tmp_path: Path, include_exploratory: bool) -> None:
    names = ["normal.f90", "features/feature.f90", "more/probe.f90",
             "more/nested/probe_nested.f90", "stash/old.f90", "more/stash/old.f90"]
    for name in names:
        source = tmp_path / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.touch()
    expected = {"normal.f90", "features/feature.f90"}
    if include_exploratory:
        expected.update({"more/probe.f90", "more/nested/probe_nested.f90"})
    assert {p.relative_to(tmp_path).as_posix()
            for p in execution_sources(tmp_path, include_exploratory)} == expected
