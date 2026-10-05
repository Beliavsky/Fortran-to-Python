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


def test_module_only_report(tmp_path, capsys):
    source = tmp_path / "library.f90"
    source.write_text("module m\nend module m\n")
    destination = tmp_path / "reports"
    assert batch.main([str(source), "--run-diff", "--out-dir", str(destination)]) == 0
    import json
    report = json.loads(next(destination.glob("*/results.json")).read_text())
    assert report["complete"]
    assert report["summary"] == {"skipped_library": 1}
    last_line = capsys.readouterr().out.splitlines()[-1]
    assert last_line.startswith("Time: total ")
    assert "Fortran compile 0.000s" in last_line
    assert "Python run 0.000s" in last_line


def test_timing_summary_totals_all_cases():
    stages = {name: {"elapsed_seconds": value} for name, value in
              zip(("compile", "fortran_run", "translate", "python_run", "comparison"), (1, 2, 3, 4, 0.5))}
    summary = batch.timing_summary([{"stages": stages}, {"stages": stages}], 25)
    assert summary == ("Time: total 25.000s | Fortran compile 2.000s | Fortran run 4.000s | "
                       "transpile 6.000s | Python run 8.000s | compare 1.000s | other 4.000s")


def test_blank_line_between_cases(tmp_path, capsys):
    for name in ("a", "b"):
        (tmp_path / f"{name}.f90").write_text(f"module {name}\nend module {name}\n")
    assert batch.main([str(tmp_path / "*.f90"), "--out-dir", str(tmp_path / "reports")]) == 0
    output = capsys.readouterr().out
    assert output.startswith("[1/2]")
    assert "\n\n[2/2]" in output


@pytest.mark.parametrize("verbose", [False, True])
def test_successful_group_and_data_isolation(tmp_path, monkeypatch, capsys, verbose):
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
                              run_diff=True, compile=False, compiler="gfortran -O0", rtol=1e-9, atol=1e-11,
                              verbose=verbose)
    directory = tmp_path / "work"
    result = batch.evaluate(sources, directory, args)
    assert result["outcome"] == "pass"
    assert result["stages"]["comparison"]["status"] == "match"
    assert commands[0][2] == str(directory / "python" / "combined.f90")
    assert (directory / "fortran" / "input.txt").read_text() == "data"
    assert (directory / "python" / "input.txt").read_text() == "data"
    assert not (tmp_path / "main_f.py").exists()
    printed = capsys.readouterr().out
    if verbose:
        for label in ("Translation", "Fortran compilation", "Fortran", "Python"):
            assert f"{label} command:" in printed
            assert f"{label} output:" in printed
            assert f"{label}: pass (0.000s)" in printed
        assert "Comparison: match" in printed
    else:
        assert printed == ""


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


@pytest.mark.parametrize('verbose', [False, True])
def test_failures_only_keeps_diagnostics_and_complete_reports(tmp_path, monkeypatch, capsys, verbose):
    import json
    names = ['a_pass', 'b_fail', 'c_skip', 'd_warning', 'e_mismatch', 'f_timeout']
    for name in names:
        (tmp_path / f'{name}.f90').write_text('program p\nend program\n')

    def fake_evaluate(sources, directory, args):
        name = sources[0].stem
        stages = {stage: {'status': 'not_requested'} for stage in
                  ('compile', 'fortran_run', 'translate', 'python_run', 'comparison')}
        stages['translate'] = {'status': 'pass', 'stdout': 'successful translation',
                               'stderr': '', 'elapsed_seconds': 0.1}
        stages['fortran_run'] = {'status': 'pass', 'stdout': 'reference output\n'}
        stages['python_run'] = {'status': 'pass', 'stdout': 'python output\n'}
        stages['comparison'] = {'status': 'match'}
        outcome, classification = 'pass', 'program'
        if name == 'b_fail':
            stages['translate'].update(status='fail', stderr='translation error')
            outcome = 'translate_fail'
        elif name == 'c_skip':
            outcome, classification = 'skipped_library', 'library_only'
        elif name == 'd_warning':
            stages['translate']['stderr'] = 'Warning: suspicious input'
        elif name == 'e_mismatch':
            stages['comparison'] = {'status': 'mismatch', 'detail': 'first mismatch line: 1'}
            outcome = 'comparison_mismatch'
        elif name == 'f_timeout':
            stages['python_run'].update(status='timeout', stdout='partial output\n')
            outcome = 'python_run_timeout'
        if args.verbose:
            print(f'VERBOSE {name}: successful translation; reference output; python output')
            for stage in stages.values():
                if stage.get('stderr'):
                    print(stage['stderr'])
        return {'sources': list(map(str, sources)), 'work_dir': str(directory),
                'classification': classification, 'stages': stages, 'outcome': outcome}

    monkeypatch.setattr(batch, 'evaluate', fake_evaluate)
    destination = tmp_path / 'reports'
    args = [str(tmp_path / '*.f90'), '--run-diff', '--failures-only', '--out-dir', str(destination)]
    if verbose:
        args.append('--verbose')
    assert batch.main(args) == 1
    printed = capsys.readouterr().out
    assert '[1/6] Checking...' in printed
    assert 'a_pass.f90' not in printed and 'VERBOSE a_pass' not in printed
    for name in names[1:]:
        assert f'{name}.f90' in printed
    assert 'translation error' in printed and 'Warning: suspicious input' in printed
    assert 'skipped_library' in printed and 'python_run_timeout' in printed
    assert 'reference output' in printed and 'python output' in printed
    if not verbose:
        assert 'first mismatch line: 1' in printed and 'partial output' in printed
    assert printed.splitlines()[-1].startswith('Time: total ')
    report_path = next(destination.glob('*/results.json'))
    report = json.loads(report_path.read_text())
    assert report['complete'] and report['completed_cases'] == 6
    assert report['options']['failures_only'] is True
    assert report['cases'][0]['stages']['translate']['stdout'] == 'successful translation'
    assert report['cases'][0]['stages']['comparison']['status'] == 'match'
    assert 'a_pass.f90' in report_path.with_name('results.txt').read_text()


def test_failures_only_retains_stdout_warnings(tmp_path, monkeypatch, capsys):
    source = tmp_path / 'warn.f90'
    source.write_text('program p\nend program\n')

    def fake_stage(command, cwd, timeout):
        Path(command[-1]).write_text('print(1)')
        return {'status': 'pass', 'stdout': 'normal output\nWarning: review this\n',
                'stderr': '', 'elapsed_seconds': 0.0}

    monkeypatch.setattr(batch, 'stage', fake_stage)
    assert batch.main([str(source), '--failures-only', '--out-dir', str(tmp_path / 'reports')]) == 0
    printed = capsys.readouterr().out
    assert 'warn.f90' in printed and 'Warning: review this' in printed
    assert 'normal output' not in printed
