import pytest

from xbatch_terse import main, terse_text


def test_removes_progress_but_preserves_failure_and_summary():
    source = '''[1/3] Checking...

[2/3] Checking...
[2/3] bad.f90
  python_run_fail
Traceback (most recent call last):
  File "bad.py", line 1
NameError: name 'x' is not defined

[3/3] Checking...

Reports: reports/run
{"pass": 2, "python_run_fail": 1}
Time: total 1.000s
'''
    expected = source[source.index('[2/3] bad.f90'):].replace('[3/3] Checking...\n\n', '')
    assert terse_text(source) == expected


def test_collapses_blank_lines_without_changing_nonprogress_text():
    assert terse_text('\n\n[1/2] Checking...\n\n\n[2/2] Checking...\n\n') == ''
    assert terse_text('a\n\n\n\nb\n\n') == 'a\n\nb\n'
    assert terse_text('  [1/2] Checking...  \nChecking...\n[1/2] file.f90\n') == 'Checking...\n[1/2] file.f90\n'


def test_default_output_and_input_preservation(tmp_path):
    source = tmp_path / 'results.txt'
    source.write_text('[1/1] Checking...\nTime: total 1.000s\n', encoding='utf-8-sig')
    before = source.read_bytes()
    assert main([str(source)]) == 0
    assert (tmp_path / 'results_terse.txt').read_text() == 'Time: total 1.000s\n'
    assert source.read_bytes() == before
    with pytest.raises(SystemExit):
        main([str(source)])
    assert source.read_bytes() == before


def test_custom_output_and_rejects_input_overwrite(tmp_path):
    source = tmp_path / 'results.txt'
    source.write_text('Reports: here\n')
    target = tmp_path / 'short.txt'
    assert main([str(source), '--out', str(target)]) == 0
    assert target.read_text() == source.read_text()
    with pytest.raises(SystemExit):
        main([str(source), '--out', str(source)])


def test_overwrite_replaces_original_without_creating_terse_file(tmp_path):
    source = tmp_path / 'results.txt'
    source.write_text('[1/1] Checking...\n\nReports: here\nTime: total 1.000s\n')
    assert main([str(source), '--overwrite']) == 0
    assert source.read_text() == 'Reports: here\nTime: total 1.000s\n'
    assert list(tmp_path.iterdir()) == [source]
    assert main([str(source), '--overwrite']) == 0
    assert source.read_text() == 'Reports: here\nTime: total 1.000s\n'


def test_overwrite_and_out_are_mutually_exclusive(tmp_path):
    source = tmp_path / 'results.txt'
    source.write_text('original\n')
    with pytest.raises(SystemExit):
        main([str(source), '--overwrite', '--out', str(tmp_path / 'other.txt')])
    assert source.read_text() == 'original\n'


def test_failed_replacement_preserves_original_and_removes_temporary(tmp_path, monkeypatch):
    import xbatch_terse
    source = tmp_path / 'results.txt'
    source.write_text('[1/1] Checking...\nReports: here\n')
    before = source.read_bytes()

    def fail_replace(src, dst):
        assert src.parent == dst.parent == tmp_path
        assert src.read_text() == 'Reports: here\n'
        raise OSError('replacement failed')

    monkeypatch.setattr(xbatch_terse.os, 'replace', fail_replace)
    with pytest.raises(SystemExit):
        main([str(source), '--overwrite'])
    assert source.read_bytes() == before
    assert list(tmp_path.iterdir()) == [source]
