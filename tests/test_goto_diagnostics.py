"""Unimplemented jumps must be rejected, never silently dropped."""
import subprocess
import sys

import pytest

import xf2p
from xf2p import basic_f2p


@pytest.mark.parametrize('statement', [
    'goto 100', 'go to 100', 'GOTO 100', 'GO TO 100',
    'if (i == 1) goto 100', 'IF (i == 1) GO TO 100',
    'i = 1; go to 100', '20 goto 100',
    'goto &\n & 100', 'go to (100, 200), i',
    'goto destination', 'go to destination, (100, 200)',
])
def test_unsupported_jumps_are_rejected(statement):
    source = f'''program jumps
integer :: i, destination
i = 1
{statement}
i = 2
100 continue
200 continue
print *, i
end program jumps'''
    with pytest.raises(ValueError, match='GOTO control flow is not yet supported') as caught:
        basic_f2p().transpile(source)
    assert 'rewrite using structured IF/DO, EXIT or CYCLE' in str(caught.value)


def test_jump_in_external_procedure_is_rejected():
    source = '''program p
end program p
subroutine jump()
goto 100
100 continue
end subroutine jump'''
    with pytest.raises(ValueError, match='GOTO control flow'):
        basic_f2p().transpile(source)


def test_strings_comments_and_goto_variable_are_unaffected(capsys):
    source = '''program p
integer :: goto, i, gotos(1), goto10
! goto 100
goto = 3
gotos(1) = 4
goto10 = 6
i = 0
if (i == 0) goto = 5
print *, 'goto 100; go to 200', goto, gotos(1), goto10
end program p'''
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == 'goto 100; go to 200 5 4 6'


def test_array_named_goto_is_not_mistaken_for_computed_jump(capsys):
    source = '''program p
integer :: goto(2)
goto(1) = 3
if (.true.) goto(2) = 4
print *, goto
end program p'''
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.split() == ['3', '4']


def test_cli_rejects_original_wrong_result_repro_without_output(tmp_path):
    source = tmp_path / 'xgoto_spellings.f90'
    source.write_text('''program main
integer :: i
i = 1
goto 100
i = 2
100 continue
print *, i
go to 200
i = 3
200 continue
print *, i
end program main
''', encoding='utf-8')
    output = tmp_path / 'translated.py'
    result = subprocess.run(
        [sys.executable, xf2p.__file__, str(source), '--out', str(output)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'Transpile: FAIL' in result.stdout
    assert 'GOTO control flow is not yet supported' in result.stdout
    assert 'goto 100' in result.stdout
    assert 'Traceback' not in result.stderr
    assert not output.exists()
