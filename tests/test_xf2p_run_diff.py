from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import xf2p
import xf2p_batch


def test_cli_and_batch_logical_diffs(tmp_path):
    compiler = shutil.which('gfortran')
    if compiler is None:
        pytest.skip('gfortran required')
    pytest.importorskip('numpy')
    source = tmp_path / 'logical_output.f90'
    source.write_text('program demo\nlogical :: flags(3)\n'
                      'flags = [.true., .false., .true.]\n'
                      'print *, .true.\nprint *, flags\n'
                      'print *, 7, .false., 2\nend program\n')
    command = [sys.executable, str(Path(xf2p.__file__)), str(source),
               '--compiler', f'"{compiler}" -O0', '--run-diff']
    for options, expected in [([], 0), (['--diff-exact'], 1)]:
        result = subprocess.run([*command, *options], cwd=tmp_path,
                                capture_output=True, text=True, timeout=90)
        assert result.returncode == expected, result.stdout + result.stderr
        assert ('Run diff: MATCH' if expected == 0 else 'Run diff: DIFF') in result.stdout
    common = [str(source), '--compiler', f'"{compiler}" -O0',
              '--out-dir', str(tmp_path / 'batch_reports')]
    assert xf2p_batch.main([*common, '--run-diff']) == 0
    assert xf2p_batch.main([*common, '--diff-exact']) == 1


@pytest.mark.parametrize('mode', ['single', 'each', 'group'])
def test_cli_numeric_and_exact_diffs(tmp_path, mode):
    compiler = shutil.which('gfortran')
    if compiler is None:
        pytest.skip('gfortran required')
    pytest.importorskip('numpy')
    main = tmp_path / 'main.f90'
    arguments = []
    if mode == 'group':
        provider = tmp_path / 'provider.f90'
        provider.write_text('module provider\ncontains\nreal(8) function value()\n'
                            'value = sqrt(0.7d0)\nend function\nend module\n')
        main.write_text('program demo\nuse provider\nprint *, value()\nend program\n')
        arguments.append(str(provider))
    else:
        main.write_text('program demo\nprint *, sqrt(0.7d0)\nend program\n')
    arguments.append(str(main))
    if mode == 'each':
        arguments.append('--mode-each')
    command = [sys.executable, str(Path(xf2p.__file__)), *arguments, '--compiler',
               f'"{compiler}" -O0', '--run-diff']
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Run diff: MATCH' in result.stdout
    result = subprocess.run([*command, '--diff-exact'], cwd=tmp_path, capture_output=True,
                            text=True, timeout=90)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'Run diff: DIFF' in result.stdout
    if mode == 'single':
        common = [str(main), '--out-dir', str(tmp_path / 'batch_reports')]
        assert xf2p_batch.main([*common, '--run-diff']) == 0
        assert xf2p_batch.main([*common, '--diff-exact']) == 1


@pytest.mark.parametrize('options, expected', [([], 1), (['--rtol', '.01'], 0),
                                              (['--diff-exact'], 1)])
def test_cli_exit_status_and_tolerances(tmp_path, monkeypatch, capsys, options, expected):
    source = tmp_path / 'demo.f90'
    source.write_text('print *, 1\nend\n')
    def fake_run(command, **kwargs):
        if command[0] == sys.executable:
            return subprocess.CompletedProcess(command, 0, 'value 1.001\n', 'Python warning\n')
        if str(command[0]).endswith('.exe'):
            return subprocess.CompletedProcess(command, 0, 'value 1.0\n', '')
        return subprocess.CompletedProcess(command, 0, '', '')
    monkeypatch.setattr(xf2p.subprocess, 'run', fake_run)
    monkeypatch.setattr(sys, 'argv', ['xf2p.py', str(source), '--run-diff', *options])
    assert xf2p.main() == expected
    output = capsys.readouterr().out
    assert ('Run diff: MATCH' if expected == 0 else 'Run diff: DIFF') in output


@pytest.mark.parametrize('options', [['--rtol', '-1'], ['--atol', 'nan'], ['--rtol', 'inf']])
def test_cli_rejects_invalid_tolerances(monkeypatch, options):
    monkeypatch.setattr(sys, 'argv', ['xf2p.py', 'unused.f90', *options])
    with pytest.raises(SystemExit) as exc:
        xf2p.main()
    assert exc.value.code == 2
