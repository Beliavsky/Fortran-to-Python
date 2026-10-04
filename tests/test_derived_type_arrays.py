from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

from fortran_py_runtime import (
    _f_assign_array, _f_assign_component_array, _f_component_array,
    _f_init_component_array, pack,
)
from xf2p import basic_f2p


@dataclass
class Record:
    v: int = 0
    samples: list = field(default_factory=lambda: [1, 2])


def test_projected_assignment_preserves_shape_and_snapshots_rhs():
    a = _f_init_component_array((2, 2), Record(), object)
    _f_assign_component_array(a, 'v', [[1, 3], [2, 4]])
    np.testing.assert_array_equal(_f_component_array(a, 'v'), [[1, 3], [2, 4]])
    np.testing.assert_array_equal(pack(_f_component_array(a, 'v'), True), [1, 2, 3, 4])
    _f_assign_component_array(a, 'v', 9, mask=[[True, False], [False, True]])
    np.testing.assert_array_equal(_f_component_array(a, 'v'), [[9, 3], [2, 9]])
    a[0, 0].samples[0] = 99
    assert a[1, 1].samples == [1, 2]
    with pytest.raises(ValueError, match='conformable'):
        _f_assign_component_array(a, 'v', [1, 2])
    with pytest.raises(ValueError, match='explicit subscripts'):
        _f_component_array(a, 'samples')
    empty = _f_component_array(np.empty((0, 2), dtype=object), 'v', dtype=int)
    assert empty.shape == (0, 2) and empty.dtype == np.dtype(int)


@pytest.mark.parametrize('allocated', [True, False])
def test_whole_array_assignment_copies_derived_values(allocated):
    a = _f_init_component_array((2,), Record(), object)
    b = _f_assign_array(_f_init_component_array((2,), Record(), object) if allocated else None, a)
    b[0].samples[0] = 99
    assert a[0].samples == b[1].samples == [1, 2]
    seed = Record()
    b = _f_assign_array(b, seed)
    b[0].samples[0] = 77
    assert seed.samples == b[1].samples == [1, 2]


def test_pack_vector_and_fortran_order():
    np.testing.assert_array_equal(pack([[1, 3], [2, 4]], True, [9, 8, 7, 6, 5]), [1, 2, 3, 4, 5])
    np.testing.assert_array_equal(pack([[1, 3], [2, 4]], [[False, True], [True, False]]), [2, 3])
    with pytest.raises(ValueError):
        pack([1, 2], True, [9])


def test_derived_array_components_output(capsys):
    source = (Path(__file__).parent / 'cases/features/derived_type_array_components.f90').read_text()
    namespace = {'__name__': '__main__'}
    exec(basic_f2p().transpile(source), namespace)
    assert capsys.readouterr().out.splitlines() == [
        '10 100 20 200 30 300', '10 20 30', '200 300', '600',
        '1 10 2 20 3 31 4 41', '20 31 41',
    ]


def test_nested_component_copy_and_output(capsys):
    source = '''program test
implicit none
type leaf
integer :: v = 2
integer :: samples(2) = [3,4]
end type
type record
type(leaf) :: child
end type
type(record) :: x(2), y(2)
x%child%v = [10,20]
x(1)%child%samples(1) = 99
y = x
y(1)%child%v = 77
print *, x
print *, y
end program
'''
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == ['10 99 4 20 3 4', '77 99 4 20 3 4']


def test_saved_derived_array_initialization(capsys):
    source = '''program test
type dt
integer :: v = 0
end type
call update()
call update()
contains
subroutine update()
type(dt), save :: x(2)
x%v = x%v + 1
print *, x%v
end subroutine
end program
'''
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == ['1 1', '2 2']


def test_component_assignment_conversion_and_scalar_broadcast(capsys):
    source = '''program test
type dt
integer :: v
character(len=3) :: label
end type
type(dt) :: x(2), seed
x%v = [1.9, -1.9]
x%label = 'ab'
print *, pack(array=x%v, mask=.true., vector=[9,8,7])
print *, len(x(1)%label)
seed = dt(5, 'xyz')
x = seed
x(1)%v = 99
print *, x%v
print *, seed
end program
'''
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == ['1 -1 7', '3', '99 5', '5 xyz']
