"""DATA initialization must preserve values, array order, and implicit SAVE."""
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

import xf2p
from xf2p import basic_f2p


def execute(source, capsys):
    namespace = {'__name__': '__main__'}
    exec(basic_f2p().transpile(source), namespace)
    return capsys.readouterr().out


def test_data_scalar_array_and_saved_procedures(capsys):
    source = (Path(__file__).parent / 'cases/features/data_initializers.f90').read_text()
    lines = [line.split() for line in execute(source, capsys).splitlines()]
    assert lines == [
        ['5', '5', '5', '2.5', '7.25'], ['[fortran', ']'],
        ['10', '20', '30'], ['1', '2', '3', '4', '5', '6'],
        ['1', '3', '5', '2', '4', '6'], ['2', '1.0', '-2.0'],
        ['[a/b', '][x,y', '][1234]'], ['7'],
        ['1', '2', '3'], ['2', '4', '5'], ['3', '7', '8'], ['11'], ['12'],
    ]


def test_data_repetition_is_not_expanded_into_large_generated_source():
    source = '''module m
integer :: a(1000000)
data a /1000000*3/
end module m'''
    generated = basic_f2p().transpile(source)
    assert 'np.full(1000000, 3' in generated
    assert len(generated) < 30000
    namespace = {'__name__': 'test_data'}
    exec(generated, namespace)
    assert namespace['a'].shape == (1000000,)
    assert np.all(namespace['a'] == 3)


def test_data_character_logical_complex_and_typed_scalars():
    source = '''module m
integer :: n
real :: x
complex :: z
logical :: flags(3)
character(len=4) :: words(3)
DATA N /5/ x /2/ z /(1.0, -2.0)/
data flags /2*.true., .false./
data words /'a/b', 'x,y', '123456'/
end module m'''
    namespace = {'__name__': 'test_data'}
    exec(basic_f2p().transpile(source), namespace)
    assert namespace['n'] == 5 and type(namespace['n']) is int
    assert namespace['x'] == 2 and isinstance(namespace['x'], (float, np.floating))
    assert namespace['z'] == complex(1, -2)
    assert namespace['flags'].tolist() == [True, True, False]
    assert namespace['words'].tolist() == ['a/b ', 'x,y ', '1234']


def test_data_statement_after_executable_line_still_initializes_before_execution(capsys):
    # Legacy placement is permitted by gfortran; DATA is not an assignment
    # that should overwrite an executable update.
    source = '''program p
integer :: n
n = n + 1
data n /5/
print *, n
end program'''
    assert execute(source, capsys).split() == ['6']


def test_variable_named_data_and_string_literals_are_unaffected(capsys):
    source = '''program p
integer :: data(2)
data (1) = 5
data(2) = 6
print *, 'data n /0/; DATA a /3*1/', data
end program'''
    assert execute(source, capsys).split() == ['data', 'n', '/0/;', 'DATA', 'a', '/3*1/', '5', '6']


def test_character_data_with_assignment_and_statement_delimiters(capsys):
    source = '''program p
character(len=9) :: text
data text /'a=b; x/y'/
print *, '[' // text // ']'
end program'''
    assert execute(source, capsys).strip() == '[a=b; x/y ]'


def test_multiple_data_statements_on_one_line(capsys):
    source = 'program p\ninteger :: n,m\ndata n /5/; data m /6/\nprint *, n,m\nend program p'
    assert execute(source, capsys).split() == ['5', '6']


@pytest.mark.parametrize('statement', ['data n /5/; print *, n', 'n = 6; data n /5/'])
def test_mixed_statement_line_is_rejected_instead_of_dropping_execution(statement):
    with pytest.raises(ValueError, match='split the line'):
        basic_f2p().transpile(f'program p\ninteger :: n\n{statement}\nend program p')


@pytest.mark.parametrize('declaration, statement, message', [
    ('integer :: a(3)', 'data (a(i), i=1,3) /3*1/', 'implied-DO'),
    ('integer :: a(3)', 'data a(1) /1/', 'partial objects'),
    ('integer :: a(3), n', 'data a, n /1,2,3,4/', 'mixing arrays'),
    ('integer :: n, m', 'data n, m /1/', 'count mismatch'),
    ('integer :: n = 5', 'data n /1/', 'duplicate initialization'),
    ('integer :: n', 'data n /1/\ndata n /2/', 'duplicate initialization'),
    ('integer :: a(3)', 'data a /n*1/', 'literal nonnegative integer'),
    ('integer :: n', 'data absent /1/', 'explicit declaration'),
    ('integer, pointer :: n', 'data n /1/', 'not supported'),
    ('integer :: n', 'data n /1', 'malformed'),
])
def test_unsupported_data_is_rejected(declaration, statement, message):
    with pytest.raises(ValueError, match=message):
        basic_f2p().transpile(f'program p\n{declaration}\n{statement}\nend program p')


def test_data_in_unrecognized_subroutine_cannot_be_silently_lost():
    source = '''program p
end program p
subroutine counter
integer :: n
data n /0/
end subroutine counter'''
    with pytest.raises(ValueError, match='unsupported program unit'):
        basic_f2p().transpile(source)


def test_array_data_does_not_repeat_short_value_list_implicitly():
    source = 'module m\ninteger :: a(3)\ndata a /1,2/\nend module m'
    with pytest.raises(ValueError, match='reshape'):
        exec(basic_f2p().transpile(source), {'__name__': 'test_data'})


def test_cli_reports_unsupported_data_without_creating_python(tmp_path):
    source = tmp_path / 'data_partial.f90'
    source.write_text('program p\ninteger :: a(2)\ndata a(1) /1/\nend program p\n')
    output = tmp_path / 'translated.py'
    result = subprocess.run([sys.executable, xf2p.__file__, str(source), '--out', str(output)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'Transpile: FAIL' in result.stdout
    assert 'partial objects' in result.stdout
    assert not output.exists()
