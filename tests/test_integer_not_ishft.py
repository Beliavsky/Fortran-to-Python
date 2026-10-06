from pathlib import Path

import numpy as np
import pytest

from fortran_py_runtime import _f_bits
from xf2p import basic_f2p


@pytest.mark.parametrize('bits', [8,16,32,64,128])
def test_signed_width_and_zero_filled_shifts(bits):
    maximum = (1 << (bits-1))-1
    minimum = -(1 << (bits-1))
    assert _f_bits('not',0,bits=bits) == -1
    assert _f_bits('not',-1,bits=bits) == 0
    assert _f_bits('not',maximum,bits=bits) == minimum
    assert _f_bits('not',minimum,bits=bits) == maximum
    assert _f_bits('ishft',-1,shift=-1,bits=bits) == maximum
    assert _f_bits('ishft',1,shift=bits-1,bits=bits) == minimum
    assert _f_bits('ishft',-1,shift=1,bits=bits) == -2
    for shift in (bits,-bits):
        assert _f_bits('ishft',-1,shift=shift,bits=bits) == 0


def test_elemental_arrays_shapes_and_scalar_expansion():
    np.testing.assert_array_equal(_f_bits('not',[1,2,3,4]), [-2,-3,-4,-5])
    np.testing.assert_array_equal(_f_bits('ishft',[1,2,3,4],shift=[0,1,-1,2]), [1,4,1,16])
    np.testing.assert_array_equal(_f_bits('ishft',1,shift=[0,1,2,3]), [1,2,4,8])
    result = _f_bits('not',np.ones((2,3),dtype=int),bits=16)
    assert result.dtype == np.int16
    assert result.shape == (2,3)
    assert np.all(result == -2)
    assert _f_bits('not',np.empty((0,2),dtype=int)).shape == (0,2)
    assert _f_bits('ishft',np.empty(0,dtype=int),shift=1).shape == (0,)
    with pytest.raises(ValueError, match='conformable'):
        _f_bits('ishft',np.ones((2,1),dtype=int),shift=np.ones((1,2),dtype=int))


@pytest.mark.parametrize('operation,kwargs', [
    ('not',{'i':1.5}), ('not',{'i':True}),
    ('ishft',{'i':1,'shift':1.0}), ('ishft',{'i':1,'shift':33}),
    ('ishft',{'i':1,'shift':-33}),
])
def test_invalid_runtime_inputs(operation,kwargs):
    with pytest.raises((TypeError,ValueError)):
        _f_bits(operation,**kwargs)


@pytest.mark.parametrize('expr', [
    'not()', 'not(1,2)', 'not(.true.)', 'not(1.0)',
    'not(i=1,i=2)', 'ishft(1)', 'ishft(i=1,other=2)',
])
def test_invalid_intrinsic_arguments(expr):
    with pytest.raises(ValueError):
        basic_f2p().translate_expr(expr,set())


def test_fixture(capsys):
    source = (Path(__file__).parent / 'cases/features/integer_not_ishft.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__':'__main__'})
    assert capsys.readouterr().out.splitlines() == [
        '-2 -3 -4 -5', '1 4 1 16', '1 2 4 8',
        '2147483647 -2 -2147483648', '0 0', 'False True False True False',
        'True False True False False',
        '-2 -128 1 1', '-2 -32768 2',
        '9223372036854775807 -9223372036854775808',
        '-9223372036854775808 8', '8 -3', '0 0', 'not(1) ishft(1,2)',
    ]


def test_128_bit_source_and_result_models(capsys):
    exec(basic_f2p().transpile('''program main
integer(kind=16) :: wide
wide = 1
print *, not(wide), ishft(wide,127), ishft(-1_16,-1)
print *, kind(not(wide)), kind(ishft(wide,1))
end program
'''), {'__name__':'__main__'})
    assert capsys.readouterr().out.splitlines() == [
        '-2 -170141183460469231731687303715884105728 170141183460469231731687303715884105727',
        '16 16',
    ]


def test_user_procedure_named_ishft(capsys):
    exec(basic_f2p().transpile('''program main
print *, ishft(1,2)
contains
integer function ishft(i,shift)
integer :: i,shift
ishft = i+shift+100
end function
end program
'''), {'__name__':'__main__'})
    assert capsys.readouterr().out.strip() == '103'


def test_array_named_ishft(capsys):
    exec(basic_f2p().transpile('''program main
integer :: ishft(2)
ishft = [2,3]
print *, ishft(1)
end program
'''), {'__name__':'__main__'})
    assert capsys.readouterr().out.strip() == '2'
