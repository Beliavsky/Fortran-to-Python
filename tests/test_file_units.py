from pathlib import Path

import numpy as np
import pytest

import fortran_py_runtime as runtime
from xf2p import basic_f2p


@pytest.fixture(autouse=True)
def close_test_units():
    original = set(runtime._f_file_units)
    yield
    for unit in set(runtime._f_file_units) - original:
        runtime._f_file_close(unit)


def test_scratch_units_and_read_arrays():
    first = runtime._f_file_open(status='scratch')
    second = runtime._f_file_open(status='scratch')
    assert first != second and first < 0 and second < 0
    runtime._f_file(first, 'write').write('1,2\n3,4\n')
    runtime._f_file_rewind(first)
    values = runtime._f_file_read(first, [4], ['integer'])[0]
    target = np.zeros((2, 2), dtype=np.int32)
    assert runtime._f_file_read_assign(target, values) is target
    np.testing.assert_array_equal(target, [[1, 3], [2, 4]])
    with pytest.raises(EOFError):
        runtime._f_file_read(first, [1], ['integer'])
    runtime._f_file_close(first)
    with pytest.raises(OSError, match='not connected'):
        runtime._f_file(first)


def test_numeric_logical_and_section_input():
    unit = runtime._f_file_open(status='scratch')
    runtime._f_file(unit).write('7 2.5D+00 .TRUE. F\n99\n')
    runtime._f_file_rewind(unit)
    values = runtime._f_file_read(unit, [1, 1, 2], ['integer', 'real', 'logical'])
    assert values == [[7], [2.5], [True, False]]
    assert runtime._f_file_read_assign(0, values[0]) == 7
    target = np.zeros(4, dtype=bool)
    runtime._f_file_read_assign(target[::2], values[2])
    np.testing.assert_array_equal(target, [True, False, False, False])
    assert runtime._f_file_read(unit, [1], ['integer']) == [[99]]


def test_named_file_modes(tmp_path):
    path = tmp_path / 'with, comma.txt'
    runtime._f_file_open(20, file=path, status='new', action='write')
    runtime._f_file(20, 'write').write('original\n')
    runtime._f_file_close(20)
    with pytest.raises(FileExistsError):
        runtime._f_file_open(20, file=path, status='new')
    runtime._f_file_open(20, file=path, status='old', action='read')
    assert runtime._f_file(20, 'read').readline() == 'original\n'
    with pytest.raises(OSError):
        runtime._f_file(20, 'write')
    runtime._f_file_close(20)
    runtime._f_file_open(20, file=path, status='old', position='append')
    runtime._f_file(20).write('appended\n')
    runtime._f_file_close(20)
    assert path.read_text() == 'original\nappended\n'
    runtime._f_file_open(20, file=path, status='replace')
    runtime._f_file(20).write('replacement\n')
    runtime._f_file_close(20, status='delete')
    assert not path.exists()
    with pytest.raises(FileNotFoundError):
        runtime._f_file_open(20, file=path, status='old')


@pytest.mark.parametrize('options', [
    {'access': 'direct'}, {'form': 'unformatted'}, {'status': 'unsupported'},
    {'status': 'scratch', 'file': 'bad.txt'}, {'unit': -10, 'status': 'scratch'},
])
def test_unsupported_open_options(options):
    with pytest.raises(ValueError):
        runtime._f_file_open(**options)


@pytest.mark.parametrize('token,kind', [
    ('1,,2', 'integer'), ('2*3', 'integer'), ('/', 'real'), ('garbage', 'logical'),
])
def test_unsupported_or_invalid_input(token, kind):
    unit = runtime._f_file_open(status='scratch')
    runtime._f_file(unit).write(token + '\n')
    runtime._f_file_rewind(unit)
    with pytest.raises(ValueError):
        runtime._f_file_read(unit, [1], [kind])


@pytest.mark.parametrize('statement', [
    "open(unit=20,file='x',access='direct')",
    "open(unit=20,file='x',form='unformatted')",
    "open(unit=20,file='x',recl=80)",
    "read(20,'(i3)') n",
    "read(20,*,end=100) n",
])
def test_unsupported_io_is_diagnosed(statement):
    source = f'program demo\ninteger :: n\n{statement}\nend program'
    with pytest.raises(ValueError):
        basic_f2p().transpile(source)


def test_native_fixture_translation(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    source = (Path(__file__).parent / 'cases/features/file_units.f90').read_text()
    generated = basic_f2p().transpile(source)
    exec(generated, {'__name__': '__main__'})
    assert '10 20 30' in capsys.readouterr().out
    assert not runtime._f_file_units
    assert not (tmp_path / 'file_units_values.txt').exists()


def test_input_error_iostat_preserves_target(capsys):
    source = """program demo
integer :: unit, ios, n
character(len=80) :: message
n = 42
open(newunit=unit,status='scratch')
write(unit,'(a)') 'invalid integer'
rewind(unit)
read(unit,*,iostat=ios,iomsg=message) n
print *, ios > 0, len_trim(message) > 0, n
close(unit)
end program
"""
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == 'True True 42'


def test_open_filename_with_comma(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    source = """program demo
integer :: unit, n
open(newunit=unit,file='a,b.txt',status='new')
write(unit,*) 123
rewind(unit)
read(unit,*) n
print *, n
close(unit,status='delete')
end program
"""
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == '123'
    assert not (tmp_path / 'a,b.txt').exists()


def test_invalid_read_without_iostat_raises():
    source = """program demo
integer :: unit, n
open(newunit=unit,status='scratch')
write(unit,'(a)') 'invalid'
rewind(unit)
read(unit,*) n
end program
"""
    with pytest.raises(ValueError):
        exec(basic_f2p().transpile(source), {'__name__': '__main__'})


def test_io_keywords_as_variable_names(capsys):
    source = """program demo
integer :: open, close, rewind, read, write(1)
open = 1
close = 2
rewind = 3
read = 4
write(1) = 5
print *, open, close, rewind, read, write(1)
end program
"""
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == '1 2 3 4 5'


def test_empty_array_input_consumes_record():
    unit = runtime._f_file_open(status='scratch')
    runtime._f_file(unit).write('unused record\n123\n')
    runtime._f_file_rewind(unit)
    assert runtime._f_file_read(unit, [0], ['integer']) == [[]]
    assert runtime._f_file_read(unit, [1], ['integer']) == [[123]]
