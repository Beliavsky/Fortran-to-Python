from xf2p import basic_f2p


def execute(source, capsys):
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    return capsys.readouterr().out.split()


def test_allocatable_out_is_deallocated_on_entry_and_return(capsys):
    assert execute('''program main
integer, allocatable :: w(:)
w=[10,20,30]
call sub(w)
print *, allocated(w)
contains
subroutine sub(v)
integer, intent(out), allocatable :: v(:)
print *, allocated(v)
return
end subroutine
end program''', capsys) == ['False', 'False']


def test_allocatable_out_can_be_reallocated(capsys):
    assert execute('''program main
integer, allocatable :: w(:)
w=[10,20,30]
call sub(w)
print *, allocated(w), size(w), w
contains
subroutine sub(v)
integer, allocatable, intent(out) :: v(:)
print *, allocated(v)
allocate(v(2))
v=[4,5]
end subroutine
end program''', capsys) == ['False', 'True', '2', '4', '5']


def test_allocatable_inout_retains_allocation(capsys):
    assert execute('''program main
integer, allocatable :: w(:)
w=[10,20,30]
call sub(w)
print *, allocated(w), w
contains
subroutine sub(v)
integer, allocatable, intent(inout) :: v(:)
print *, allocated(v)
v(1)=7
end subroutine
end program''', capsys) == ['True', 'True', '7', '20', '30']


def test_function_allocatable_scalar_out(capsys):
    assert execute('''program main
integer, allocatable :: w
integer :: n
allocate(w)
w=3
n=f(w)
print *, n, allocated(w)
contains
integer function f(v) result(r)
integer, allocatable, intent(out) :: v
print *, allocated(v)
r=9
end function
end program''', capsys) == ['False', '9', 'False']


def test_allocatable_character_out(capsys):
    assert execute('''program main
character(len=:), allocatable :: w
w='old'
call sub(w)
print *, allocated(w), len(w), w
contains
subroutine sub(v)
character(len=:), allocatable, intent(out) :: v
print *, allocated(v)
v='newer'
end subroutine
end program''', capsys) == ['False', 'True', '5', 'newer']


def test_optional_out_presence_is_independent_of_allocation(capsys):
    assert execute('''program main
integer, allocatable :: w(:)
call sub(w)
print *, allocated(w), w
call sub(w)
print *, allocated(w), w
call sub()
contains
subroutine sub(v)
integer, allocatable, optional, intent(out) :: v(:)
print *, present(v)
if (present(v)) then
print *, allocated(v)
v=[4,5]
end if
end subroutine
end program''', capsys) == ['True', 'False', 'True', '4', '5',
                           'True', 'False', 'True', '4', '5', 'False']


def test_optional_function_out_presence(capsys):
    assert execute('''program main
integer, allocatable :: w
integer :: n
n=f(w)
print *, n, allocated(w), w
n=f()
print *, n
contains
integer function f(v) result(r)
integer, allocatable, optional, intent(out) :: v
print *, present(v)
r=9
if (present(v)) then
print *, allocated(v)
allocate(v)
v=3
end if
end function
end program''', capsys) == ['True', 'False', '9', 'True', '3', 'False', '9']
