from pathlib import Path

import numpy as np
import pytest

from fortran_py_runtime import _f_dprod
from xf2p import basic_f2p


def test_widen_before_multiplication():
    x = np.float32(1 + 2**-23)
    expected = np.float64(x) * np.float64(x)
    assert _f_dprod(x, x) == expected
    assert _f_dprod(x, x) != np.float64(x * x)
    a = np.array([x, x], dtype=np.float32)
    result = _f_dprod(a, a)
    assert result.dtype == np.float64
    np.testing.assert_array_equal(result, [expected, expected])


def test_double_precision_prevents_single_precision_overflow():
    x = np.float32(1e30)
    result = _f_dprod(x, x)
    assert np.isfinite(result)
    assert result == np.float64(x) ** 2


@pytest.mark.parametrize('left,right,expected', [
    (2.0, 3.0, 6.0),
    ([1.0, 2.0], 3.0, [3.0, 6.0]),
    (3.0, [1.0, 2.0], [3.0, 6.0]),
    ([[1.0, 2.0]], [[3.0, 4.0]], [[3.0, 8.0]]),
    (np.empty(0), 2.0, []),
])
def test_elemental_products(left, right, expected):
    np.testing.assert_array_equal(_f_dprod(left, right), expected)


def test_arrays_must_conform_without_numpy_broadcasting():
    with pytest.raises(ValueError, match='conforming shapes'):
        _f_dprod(np.ones((2, 1)), np.ones((1, 2)))


@pytest.mark.parametrize('value', [1, True, 1j, '2'])
def test_non_real_operands_rejected(value):
    with pytest.raises(TypeError, match='real operands'):
        _f_dprod(value, 2.0)


@pytest.mark.parametrize('expression', [
    'dprod()', 'dprod(1.0)', 'dprod(1.0,2.0,3.0)',
    'dprod(x=1.0,x=2.0)', 'dprod(a=1.0,y=2.0)',
])
def test_invalid_arguments_rejected(expression):
    with pytest.raises(ValueError, match='DPROD'):
        basic_f2p().translate_expr(expression, set())


def test_native_fixture(capsys):
    source = (Path(__file__).parent / 'cases/features/dprod.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    lines = capsys.readouterr().out.splitlines()
    assert lines[-3:] == ['True', '8 8', 'dprod(2.0,3.0)']
    assert [float(value) for value in lines[0].split()] == [6.0, 6.0]
    assert [float(value) for value in lines[1].split()] == [3.0, -8.0, -1.0]
    assert [float(value) for value in lines[3].split()] == [1.0, 4.0, 9.0, 16.0]


def test_user_procedure_named_dprod(capsys):
    exec(basic_f2p().transpile('''program main
print *, dprod(2.0,3.0)
contains
real function dprod(x,y)
real, intent(in) :: x,y
dprod = x + y
end function
end program
'''), {'__name__': '__main__'})
    assert float(capsys.readouterr().out.strip()) == 5.0
