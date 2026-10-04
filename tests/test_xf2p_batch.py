from pathlib import Path
import sys

import pytest

import xf2p_batch as batch


def test_numeric_comparison():
    assert batch.compare("value 1D0", "value 1.0000000001", 1e-9, 1e-11)["status"] == "match"
    assert batch.compare("19", "18", 1.0, 1.0)["status"] == "mismatch"
    assert batch.compare("label 1", "other 1", 1e-9, 1e-11)["status"] == "mismatch"
    assert batch.compare("1 2", "1", 1e-9, 1e-11)["status"] == "mismatch"


def test_library_classification(tmp_path):
    source = tmp_path / "library.f90"
    source.write_text("module m\nend module m\n")
    assert batch.library_only([source])
    source.write_text("module m\nend module m\nprogram p\nend program p\n")
    assert not batch.library_only([source])
    source.write_text("print *, 1\nend\n")
    assert not batch.library_only([source])


def test_subprocess_failure(tmp_path):
    result = batch.stage([sys.executable, "-c", "import sys; print('oops'); sys.exit(3)"], tmp_path, 10)
    assert result["status"] == "fail"
    assert result["returncode"] == 3
    assert "oops" in result["stdout"]


def test_subprocess_timeout(tmp_path):
    result = batch.stage([sys.executable, "-c", "import time; time.sleep(5)"], tmp_path, 0.1)
    assert result["status"] == "timeout"


def test_missing_executable(tmp_path):
    assert batch.stage([str(tmp_path / "missing.exe")], tmp_path, 1)["status"] == "error"


def test_invalid_inputs(tmp_path):
    with pytest.raises(SystemExit):
        batch.main([str(tmp_path / "missing*.f90")])
    with pytest.raises(SystemExit):
        batch.main(["--timeout", "nan"])


def test_module_only_report(tmp_path):
    source = tmp_path / "library.f90"
    source.write_text("module m\nend module m\n")
    destination = tmp_path / "reports"
    assert batch.main([str(source), "--run-diff", "--out-dir", str(destination)]) == 0
    import json
    report = json.loads(next(destination.glob("*/results.json")).read_text())
    assert report["complete"]
    assert report["summary"] == {"skipped_library": 1}


def test_successful_group_and_data_isolation(tmp_path, monkeypatch):
    import argparse
    sources = [tmp_path / "module.f90", tmp_path / "main.f90"]
    sources[0].write_text("module m\nend module m\n")
    sources[1].write_text("program p\nend program p\n")
    data = tmp_path / "input.txt"
    data.write_text("data")
    commands = []

    def fake_stage(command, cwd, timeout):
        commands.append(command)
        if "--out" in command:
            Path(command[-1]).write_text("print(1)")
        return {"status": "pass", "stdout": "1\n", "stderr": "", "elapsed_seconds": 0}

    monkeypatch.setattr(batch, "stage", fake_stage)
    args = argparse.Namespace(data=[data], timeout=10, run=False, run_both=False,
                              run_diff=True, compile=False, compiler="gfortran -O0", rtol=1e-9, atol=1e-11)
    directory = tmp_path / "work"
    result = batch.evaluate(sources, directory, args)
    assert result["outcome"] == "pass"
    assert result["stages"]["comparison"]["status"] == "match"
    assert commands[0][2] == str(directory / "python" / "combined.f90")
    assert (directory / "fortran" / "input.txt").read_text() == "data"
    assert (directory / "python" / "input.txt").read_text() == "data"
    assert not (tmp_path / "main_f.py").exists()


def test_real_multifile_group(tmp_path):
    import json
    import shutil
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran required")
    pytest.importorskip("numpy")
    module = tmp_path / "module.f90"
    main = tmp_path / "main.f90"
    module.write_text("module m\ncontains\ninteger function twice(n)\n"
                      "integer, intent(in) :: n\ntwice = 2*n\nend function\nend module\n")
    main.write_text("program p\nuse m\nprint *, twice(3)\nend program\n")
    destination = tmp_path / "reports"
    assert batch.main(["--out-dir", str(destination), "--run-diff", "--group",
                       str(module), str(main)]) == 0
    report = json.loads(next(destination.glob("*/results.json")).read_text())
    assert report["cases"][0]["stages"]["comparison"]["status"] == "match"
    assert not (tmp_path / "main_f.py").exists()
