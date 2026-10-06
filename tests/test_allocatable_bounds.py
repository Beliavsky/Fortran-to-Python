import gc

import numpy as np
import pytest

from fortran_py_runtime import (
    _f_allocation_bounds, _f_array_lbound, _f_array_ubound,
    _f_assign_array, _f_set_array_bounds,
)
from xf2p import basic_f2p


def execute(source, capsys):
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    return capsys.readouterr().out.splitlines()


def test_vector_bounds_and_indexing_through_allocatable_dummy(capsys):
    assert execute('''program main
integer, allocatable :: a(:)
allocate(a(-2:2))
a=[10,20,30,40,50]
call show(a)
contains
subroutine show(x)
integer, allocatable, intent(in) :: x(:)
print *, lbound(x), ubound(x), x(-2), x(0), x(2)
print *, x(-1:1)
end subroutine
end program''', capsys) == ['-2 2 10 30 50', '20 30 40']


def test_matrix_dynamic_dimension_bounds(capsys):
    assert execute('''program main
integer, allocatable :: a(:,:)
allocate(a(0:1,-1:1))
a=reshape([1,2,3,4,5,6],[2,3])
call show(a)
contains
subroutine show(x)
integer, allocatable, intent(in) :: x(:,:)
integer :: d
print *, lbound(x), ubound(x), x(0,-1), x(1,1)
do d=1,2
print *, lbound(x,dim=d), ubound(x,dim=d)
end do
end subroutine
end program''', capsys) == ['0 -1 1 1 1 6', '0 1', '-1 1']


@pytest.mark.parametrize('declaration, expected', [
    ('integer, intent(in) :: x(:)', '1 5 10 50'),
    ('integer, intent(in) :: x(0:)', '0 4 10 50'),
])
def test_ordinary_assumed_shape_rebases_bounds(declaration, expected, capsys):
    assert execute(f'''program main
integer, allocatable :: a(:)
allocate(a(-2:2))
a=[10,20,30,40,50]
call show(a)
contains
subroutine show(x)
{declaration}
print *, lbound(x), ubound(x), x(lbound(x,1)), x(ubound(x,1))
end subroutine
end program''', capsys) == [expected]


def test_reallocation_in_dummy_updates_caller_bounds(capsys):
    assert execute('''program main
integer, allocatable :: a(:)
allocate(a(-2:2))
a=5
call replace(a)
print *, lbound(a), ubound(a), a(7), a(8)
contains
subroutine replace(x)
integer, allocatable, intent(inout) :: x(:)
deallocate(x)
allocate(x(7:8))
x=[10,20]
print *, lbound(x), ubound(x)
end subroutine
end program''', capsys) == ['7 8', '7 8 10 20']


def test_out_allocation_and_move_alloc_through_dummies(capsys):
    assert execute('''program main
integer, allocatable :: a(:), b(:)
call make(a)
call transfer(a,b)
print *, allocated(a), lbound(b), ubound(b), b(-3)
contains
subroutine make(x)
integer, allocatable, intent(out) :: x(:)
allocate(x(-3:-1))
x=[7,8,9]
end subroutine
subroutine transfer(x,y)
integer, allocatable, intent(inout) :: x(:), y(:)
call move_alloc(x,y)
print *, allocated(x), lbound(y), ubound(y), y(-1)
end subroutine
end program''', capsys) == ['False -3 -1 9', 'False -3 -1 7']


def test_shape_preserving_assignment_keeps_bounds_and_resize_resets(capsys):
    assert execute('''program main
integer, allocatable :: a(:)
allocate(a(-2:2))
a=[1,2,3,4,5]
print *, lbound(a), ubound(a)
a=[7,8]
print *, lbound(a), ubound(a), a(1)
end program''', capsys) == ['-2 2', '1 2 7']


def test_source_and_mold_preserve_dummy_bounds(capsys):
    assert execute('''program main
integer, allocatable :: a(:)
allocate(a(-2:2))
a=7
call clone(a)
contains
subroutine clone(x)
integer, allocatable, intent(in) :: x(:)
integer, allocatable :: b(:), c(:)
allocate(b,source=x)
allocate(c,mold=x)
c=8
print *, lbound(b), ubound(b), b(-2)
print *, lbound(c), ubound(c), c(-2)
end subroutine
end program''', capsys) == ['-2 2 7', '-2 2 8']


def test_empty_dimensions_have_standard_inquiry_bounds(capsys):
    assert execute('''program main
integer, allocatable :: a(:,:)
allocate(a(-2:-3,4:6))
call show(a)
contains
subroutine show(x)
integer, allocatable, intent(in) :: x(:,:)
print *, lbound(x), ubound(x), size(x)
end subroutine
end program''', capsys) == ['1 4 0 6 0']


def test_runtime_metadata_is_released_with_array():
    a = _f_set_array_bounds(np.zeros(3), [-2])
    identity = id(a)
    assert _f_array_lbound(a, 1) == -2
    del a
    gc.collect()
    assert identity not in _f_allocation_bounds


@pytest.mark.parametrize('declaration, expected', [
    ('integer, allocatable, intent(in) :: x(:)', '-2 2'),
    ('integer, intent(in) :: x(:)', '1 5'),
    ('integer, intent(in) :: x(0:)', '0 4'),
])
def test_assignment_uses_rhs_association_bounds(declaration, expected, capsys):
    assert execute(f'''program main
integer, allocatable :: a(:)
allocate(a(-2:2))
a=7
call clone(a)
contains
subroutine clone(x)
{declaration}
integer, allocatable :: b(:)
b=x
print *, lbound(b), ubound(b)
end subroutine
end program''', capsys) == [expected]


def test_runtime_copies_keep_bounds_but_views_default_to_one():
    a = _f_set_array_bounds(np.arange(3), [-2])
    b = _f_assign_array(None, a)
    assert _f_array_lbound(b, 1) == -2
    assert _f_array_ubound(b, 1) == 0
    assert not np.shares_memory(a, b)
    assert _f_array_lbound(a[:], 1) == 1


def test_saved_allocatable_retains_bounds_between_calls(capsys):
    assert execute('''program main
call step()
call step()
contains
subroutine step()
integer, allocatable, save :: a(:)
if (.not. allocated(a)) then
allocate(a(-2:0))
a=5
end if
a(-2)=a(-2)+1
print *, lbound(a), ubound(a), a(-2)
end subroutine
end program''', capsys) == ['-2 0 6', '-2 0 7']
