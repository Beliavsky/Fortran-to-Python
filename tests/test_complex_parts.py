from pathlib import Path

import numpy as np
import pytest

from fortran_py_runtime import _f_set_complex_part, _f_assign_complex_part
from xf2p import basic_f2p


def test_fixture(capsys):
    source = (Path(__file__).parent / 'cases/features/complex_parts.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == [
        '3.0 4.0', '9.0 3.0 3.0 3.0', '2.0 7.0 2.0 8.0',
        '10.0 7.0 2.0 8.0', '1.0 1.0 11.0 12.0', '2.0 13.0 2.0 2.0',
        '21.0 22.0 5.0 14.0 1.0 15.0', '31.0 31.0 32.0 32.0 33.0 5.0',
        '41.0 4.0', '1.0 44.0', '4 8 4', 'z.re z.im',
    ]


def test_scalar_and_array_helpers():
    assert _f_set_complex_part(1+2j, 3, 'real') == 3+2j
    assert _f_set_complex_part(1+2j, 4, 'imag') == 1+4j
    a = np.array([1+2j, 3+4j])
    result = _f_set_complex_part(a, [5, 6], 'real')
    assert result is a
    np.testing.assert_array_equal(a, [5+2j, 6+4j])
    _f_assign_complex_part(a, 0, 8, 'imag')
    assert a[0] == 5+8j


def test_vector_selection_writes_back():
    a = np.array([1+2j, 3+4j, 5+6j])
    _f_assign_complex_part(a, np.array([0, 2]), [7, 9], 'real')
    np.testing.assert_array_equal(a, [7+2j, 3+4j, 9+6j])


def test_masked_update_preserves_other_part_and_aliases():
    a = np.array([1+2j, 3+4j])
    alias = a.view()
    _f_set_complex_part(a, 9, 'imag', mask=[False, True])
    np.testing.assert_array_equal(alias, [1+2j, 3+9j])


def test_rhs_can_use_other_part():
    a = np.array([1+2j, 3+4j])
    _f_set_complex_part(a, a.imag, 'real')
    np.testing.assert_array_equal(a, [2+2j, 4+4j])


def test_subscript_function_evaluated_once(capsys):
    exec(basic_f2p().transpile('''program main
complex :: z(2)
integer :: calls
calls = 0
z = (1.0,2.0)
z(next_index())%re = 7.0
print *, calls, z(2)%re, z(2)%im
contains
integer function next_index()
calls = calls + 1
next_index = 2
end function
end program
'''), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == '1 7.0 2.0'


def test_projected_complex_part_assignment(capsys):
    exec(basic_f2p().transpile('''program main
type :: box
complex :: z
end type
type(box) :: records(2)
records%z = (2.0,3.0)
records%z%re = 1.0
print *, records%z%re, records%z%im
end program
'''), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == '1.0 1.0 3.0 3.0'


def test_integer_fields_named_re_im_keep_integer_division(capsys):
    exec(basic_f2p().transpile('''program main
type :: box
integer :: re, im
end type
type(box) :: b
b%re = 9
b%im = 2
print *, b%re / b%im
end program
'''), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == '4'


def test_scalar_untouched_part_preserves_special_values():
    result = _f_set_complex_part(complex(float('inf'), -0.0), 3, 'imag')
    assert np.isinf(result.real) and result.imag == 3
    result = _f_set_complex_part(complex(1, -0.0), 2, 'real')
    assert result.real == 2 and np.signbit(result.imag)


def test_complex_part_forall_is_diagnosed():
    with pytest.raises(ValueError, match='unsupported FORALL assignment target'):
        basic_f2p().transpile('''program main
complex :: z(3)
integer :: i
z = (1.0,2.0)
forall(i=1:3) z(i)%re = real(i)
end program
''')


def test_derived_parent_subscript_evaluated_once(capsys):
    exec(basic_f2p().transpile('''program main
type :: box
complex :: z
end type
type(box) :: records(2)
integer :: calls
calls = 0
records(2)%z = (1.0,2.0)
records(next_index())%z%im = 7.0
print *, calls, records(2)%z%re, records(2)%z%im
contains
integer function next_index()
calls = calls + 1
next_index = 2
end function
end program
'''), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == '1 1.0 7.0'
