from pathlib import Path

import numpy as np
import pytest

from fortran_py_runtime import _f_bits
from xf2p import basic_f2p


@pytest.mark.parametrize('bits', [8, 16, 32, 64, 128])
def test_rotations_preserve_integer_width(bits):
    minimum = -(1 << (bits - 1))
    assert _f_bits('ishftc', 1, shift=-1, bits=bits) == minimum
    assert _f_bits('ishftc', minimum, shift=1, bits=bits) == 1
    assert _f_bits('ishftc', -1, shift=3, bits=bits) == -1
    for shift in (0, bits, -bits):
        assert _f_bits('ishftc', minimum, shift=shift, bits=bits) == minimum
    assert _f_bits('ishftc', 11, shift=1, size=3, bits=bits) == 14
    assert _f_bits('ishftc', 11, shift=-1, size=3, bits=bits) == 13
    assert _f_bits('ishftc', -5, shift=1, size=3, bits=bits) == -2


def test_elemental_size_and_conformability():
    np.testing.assert_array_equal(
        _f_bits('ishftc', [1,2,3,4], shift=[0,1,-1,2], size=[1,2,3,4]), [1,1,5,1])
    np.testing.assert_array_equal(_f_bits('ishftc', 1, shift=-1, size=[1,2,3,4]), [1,2,4,8])
    result = _f_bits('ishftc', np.ones((2,3), dtype=int), shift=-1, bits=16)
    assert result.dtype == np.int16
    assert result.shape == (2,3)
    assert np.all(result == -32768)
    assert _f_bits('ishftc', np.empty((0,2),dtype=int), shift=1).shape == (0,2)
    with pytest.raises(ValueError, match='conformable'):
        _f_bits('ishftc', np.ones((2,1),dtype=int), shift=1, size=np.ones((1,2),dtype=int))


@pytest.mark.parametrize('kwargs', [
    {'i':True,'shift':1}, {'i':1.5,'shift':1}, {'i':1,'shift':1.0},
    {'i':1,'shift':1,'size':True}, {'i':1,'shift':1,'size':2.0},
    {'i':1,'shift':1,'size':0}, {'i':1,'shift':1,'size':33},
    {'i':1,'shift':4,'size':3}, {'i':1,'shift':-4,'size':3},
])
def test_invalid_runtime_arguments(kwargs):
    with pytest.raises((TypeError, ValueError)):
        _f_bits('ishftc', **kwargs)


@pytest.mark.parametrize('expr', ['ishftc(1)', 'ishftc(1,2,3,4)',
    'ishftc(.true.,1)', 'ishftc(1.0,1)', 'ishftc(i=1,other=2)'])
def test_invalid_source_arguments(expr):
    with pytest.raises(ValueError):
        basic_f2p().translate_expr(expr,set())


def test_fixture(capsys):
    source = (Path(__file__).parent / 'cases/features/integer_ishftc.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__':'__main__'})
    assert capsys.readouterr().out.splitlines() == [
        '1 1 5 1', '1 4 -2147483647 16', '1 2 4 8', '14 13', '-1 1 1',
        '-128 1', '-32768 2', '-9223372036854775808', '8 -3', '0']


def test_128_bit_model(capsys):
    exec(basic_f2p().transpile('''program main
integer(kind=16) :: wide
wide = 1
print *, ishftc(wide,-1), kind(ishftc(wide,-1))
end program
'''), {'__name__':'__main__'})
    assert capsys.readouterr().out.strip() == '-170141183460469231731687303715884105728 16'


def test_user_procedure_and_array_named_ishftc(capsys):
    exec(basic_f2p().transpile('''program main
print *, ishftc(1,2)
contains
integer function ishftc(i,shift)
integer :: i,shift
ishftc = i+shift+100
end function
end program
'''), {'__name__':'__main__'})
    exec(basic_f2p().transpile('''program main
integer :: ishftc(2)
ishftc = [10,20]
print *, ishftc(2)
end program
'''), {'__name__':'__main__'})
    assert capsys.readouterr().out.splitlines() == ['103','20']
