from pathlib import Path

import numpy as np
import pytest

from fortran_py_runtime import _f_bits
from xf2p import basic_f2p


OPERATIONS = ('popcnt', 'poppar', 'leadz', 'trailz')


@pytest.mark.parametrize('bits', [8, 16, 32, 64, 128])
def test_counts_at_word_boundaries(bits):
    assert [_f_bits(op,0,bits=bits) for op in OPERATIONS] == [0,0,bits,bits]
    assert [_f_bits(op,-1,bits=bits) for op in OPERATIONS] == [bits,0,0,0]
    minimum = -(1 << (bits-1))
    assert [_f_bits(op,minimum,bits=bits) for op in OPERATIONS] == [1,1,0,bits-1]
    assert [_f_bits(op,-2,bits=bits) for op in OPERATIONS] == [bits-1,1,0,1]
    for pos in range(bits-1):
        assert [_f_bits(op,1 << pos,bits=bits) for op in OPERATIONS] == [1,1,bits-pos-1,pos]


def test_all_eight_bit_values():
    values = np.arange(-128,128)
    binary = [format(int(value) & 255, '08b') for value in values]
    expected = ([s.count('1') for s in binary], [s.count('1') % 2 for s in binary],
                [len(s)-len(s.lstrip('0')) for s in binary],
                [len(s)-len(s.rstrip('0')) for s in binary])
    for op, reference in zip(OPERATIONS,expected):
        np.testing.assert_array_equal(_f_bits(op,values,bits=8),reference)


@pytest.mark.parametrize('operation', OPERATIONS)
def test_arrays_and_default_result_kind(operation):
    result = _f_bits(operation,np.array([[0,1],[-1,-2]],dtype=object),bits=128)
    assert result.shape == (2,2)
    assert result.dtype == np.int32
    assert isinstance(_f_bits(operation,1,bits=8),np.int32)
    assert _f_bits(operation,np.empty((0,2),dtype=int)).shape == (0,2)
    for bad in (True,1.5):
        with pytest.raises(TypeError,match='INTEGER'):
            _f_bits(operation,bad)


@pytest.mark.parametrize('operation', OPERATIONS)
def test_invalid_source_arguments(operation):
    for args in ('', '1,2', '.true.', '1.0', 'unknown=1', 'i=1,i=2'):
        with pytest.raises(ValueError):
            basic_f2p().translate_expr(f'{operation}({args})',set())


def test_fixture(capsys):
    source = (Path(__file__).parent / 'cases/features/integer_bit_counts.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__':'__main__'})
    assert capsys.readouterr().out.splitlines() == [
        '1 1 2 1 1 1 0 1', '31 30 30 29 0 1 0 2', '0 0 32 32', '32 0 0 0',
        '8 0 0 0', '16 16', '64 0', '4 4', '4 4', '32 -65', '63 0 63', '0 0 0 0',
        'popcnt(1) poppar(1) leadz(1) trailz(1)']


def test_128_bit_source_and_nested_result_kind(capsys):
    exec(basic_f2p().transpile('''program main
integer(kind=16) :: wide
wide = -1
print *, popcnt(wide), poppar(wide), leadz(wide), trailz(wide)
print *, kind(popcnt(wide)), kind(poppar(wide)), kind(leadz(wide)), kind(trailz(wide))
print *, bit_size(popcnt(wide)), popcnt(not(0_16))
end program
'''), {'__name__':'__main__'})
    assert capsys.readouterr().out.splitlines() == ['128 0 0 0','4 4 4 4','32 128']


@pytest.mark.parametrize('operation', OPERATIONS)
def test_user_procedure_and_array_shadowing(operation,capsys):
    exec(basic_f2p().transpile(f'''program main
print *, {operation}(1)
contains
integer function {operation}(i)
integer :: i
{operation} = i+100
end function
end program
'''), {'__name__':'__main__'})
    exec(basic_f2p().transpile(f'''program main
integer :: {operation}(2)
{operation} = [10,20]
print *, {operation}(2)
end program
'''), {'__name__':'__main__'})
    assert capsys.readouterr().out.splitlines() == ['101','20']
