import numpy as np
import pytest

from fortran_py_runtime import _f_shape, _f_rank
from xf2p import basic_f2p


@pytest.mark.parametrize('value, shape, rank', [
    (7, [], 0), ('text', [], 0), ([1, 2, 3], [3], 1),
    (np.zeros((2, 3)), [2, 3], 2), (np.zeros((0, 3)), [0, 3], 2),
    (np.zeros((2, 3, 4)), [2, 3, 4], 3),
])
def test_scalar_array_and_empty_inquiries(value, shape, rank):
    assert _f_shape(value).tolist() == shape
    assert _f_shape(value).ndim == 1
    assert _f_shape(value).dtype == np.int32
    assert _f_rank(value) == rank


@pytest.mark.parametrize('kind', [1, 2, 4, 8])
def test_shape_integer_kind(kind):
    result = _f_shape(np.zeros((2, 3)), kind=kind)
    assert result.dtype == np.dtype(f'int{kind * 8}')
    assert result.tolist() == [2, 3]


def test_shape_and_rank_require_runtime_values_when_rank_unknown():
    with pytest.raises(ValueError, match='allocated'):
        _f_shape(None)
    with pytest.raises(ValueError, match='not yet supported'):
        _f_rank(None)
    with pytest.raises(ValueError, match='integer kind'):
        _f_shape([1], kind=16)


def test_keyword_arguments_sections_and_scalar_shape(capsys):
    source = '''program p
use iso_fortran_env, only: int64
integer :: a(-1:1, 0:1)
a = 7
print *, shape(source=a, kind=int64)
print *, shape(a, 8)
print *, rank(a=a)
print *, shape(a(-1:1:2, :))
print *, rank(a(:, 0))
print *, size(shape(7)), rank(7)
end program'''
    namespace = {'__name__': 'shape_test'}
    exec(basic_f2p().transpile(source), namespace)
    namespace['main']()
    assert capsys.readouterr().out.split() == ['3', '2', '3', '2', '2', '2', '2', '1', '0', '0']


def test_known_rank_of_unallocated_objects(capsys):
    source = '''program p
real, allocatable :: a(:, :)
real, allocatable :: scalar
print *, rank(a), rank(scalar)
end program'''
    namespace = {'__name__': 'rank_test'}
    exec(basic_f2p().transpile(source), namespace)
    namespace['main']()
    assert capsys.readouterr().out.split() == ['2', '0']


def test_rank_in_specification_expressions_before_storage_initialization(capsys):
    source = '''module m
integer :: a(2, 3)
integer, parameter :: r = rank(a)
end module
program p
use m, only: r
real, allocatable :: b(:, :, :)
integer, parameter :: s = rank(b)
print *, r, s
end program'''
    namespace = {'__name__': 'rank_test'}
    exec(basic_f2p().transpile(source), namespace)
    namespace['main']()
    assert capsys.readouterr().out.split() == ['2', '3']


@pytest.mark.parametrize('expression', ['shape()', 'shape(a, bad=8)', 'rank(a, kind=8)', 'rank(a, a)'])
def test_invalid_inquiry_arguments_are_rejected(expression):
    with pytest.raises(ValueError, match='Invalid arguments'):
        basic_f2p().transpile(f'program p\ninteger :: a(2)\nprint *, {expression}\nend program')


def test_select_rank_is_rejected_instead_of_executing_all_branches():
    source = '''program p
call describe(7)
contains
subroutine describe(x)
integer :: x(..)
select rank(x)
rank(0)
print *, x
rank default
print *, 0
end select
end subroutine
end program'''
    with pytest.raises(ValueError, match='SELECT RANK is not yet supported'):
        basic_f2p().transpile(source)
