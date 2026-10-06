import pytest

from xf2p import basic_f2p


def execute(source, capsys):
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    return capsys.readouterr().out.split()


@pytest.mark.parametrize('intent', ['', ', intent(in)', ', intent(inout)', ', intent(out)'])
@pytest.mark.parametrize('shape', ['', '(:)'])
def test_presence_with_omitted_unallocated_and_allocated_actuals(intent, shape, capsys):
    allocation = 'allocate(a(2))' if shape else 'allocate(a)'
    source = f'''program main
integer, allocatable :: a{shape}
call show()
call show(a)
{allocation}
a=7
call show(a)
contains
subroutine show(v)
integer, optional, allocatable{intent} :: v{shape}
print *, present(v)
if (present(v)) print *, allocated(v)
end subroutine
end program
'''
    assert execute(source, capsys) == [
        'False', 'True', 'False', 'True', 'False' if intent == ', intent(out)' else 'True',
    ]


def test_function_presence_and_reallocation(capsys):
    assert execute('''program main
integer, allocatable :: a(:)
integer :: result
print *, inspect(), inspect(a)
result=populate(a)
print *, result, allocated(a), a
print *, inspect(a)
contains
integer function inspect(v) result(r)
integer, allocatable, optional, intent(in) :: v(:)
r=-1
if (present(v)) then
r=0
if (allocated(v)) r=size(v)
end if
end function
integer function populate(v) result(r)
integer, allocatable, optional, intent(inout) :: v(:)
r=0
if (present(v)) then
v=[4,5]
print *, present(v), allocated(v)
r=size(v)
end if
end function
end program''', capsys) == ['-1', '0', 'True', 'True', '2', 'True', '4', '5', '2']


@pytest.mark.parametrize('intent', ['in', 'inout', 'out'])
def test_forwarding_omitted_and_unallocated_dummies(intent, capsys):
    assert execute(f'''program main
integer, allocatable :: a(:)
call relay()
call relay(a)
a=[4,5]
call relay(a)
contains
subroutine relay(v)
integer, allocatable, optional, intent({intent}) :: v(:)
call show(v)
print *, present(v)
end subroutine
subroutine show(w)
integer, allocatable, optional, intent(in) :: w(:)
print *, present(w)
if (present(w)) print *, allocated(w)
end subroutine
end program''', capsys) == [
        'False', 'False', 'True', 'False', 'True',
        'True', 'False' if intent == 'out' else 'True', 'True',
    ]


def test_unallocated_component_actual(capsys):
    assert execute('''program main
type :: item
integer, allocatable :: data(:)
end type
type(item) :: x
call show(x%data)
x%data=[4,5]
call show(x%data)
contains
subroutine show(v)
integer, optional, allocatable, intent(in) :: v(:)
print *, present(v), allocated(v)
end subroutine
end program''', capsys) == ['True', 'False', 'True', 'True']


def test_deallocation_does_not_change_presence(capsys):
    assert execute('''program main
integer, allocatable :: a(:)
a=[4,5]
call clear(a)
print *, allocated(a)
contains
subroutine clear(v)
integer, optional, allocatable, intent(inout) :: v(:)
print *, present(v), allocated(v)
deallocate(v)
print *, present(v), allocated(v)
end subroutine
end program''', capsys) == ['True', 'True', 'True', 'False', 'False']


def test_type_bound_optional_allocatable_default(capsys):
    assert execute('''module m
type :: item
contains
procedure :: show
end type
contains
subroutine show(this, v)
class(item), intent(in) :: this
integer, allocatable, optional, intent(in) :: v(:)
print *, present(v)
if (present(v)) print *, allocated(v)
end subroutine
end module
program main
use m
type(item) :: x
integer, allocatable :: a(:)
call x%show()
call x%show(a)
a=[4,5]
call x%show(v=a)
end program''', capsys) == ['False', 'True', 'False', 'True', 'True']
