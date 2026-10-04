import pytest

from xf2p import basic_f2p


def execute(source, capsys):
    namespace = {"__name__": "block_test"}
    exec(basic_f2p().transpile(source), namespace)
    namespace["main"]()
    return capsys.readouterr().out.split()


def test_nested_and_sibling_blocks_preserve_outer_bindings(capsys):
    source = '''program blocks
integer :: x
x = 10
block
integer :: x
x = 20
block
integer :: x
x = 30
print *, x
end block
print *, x
end block
other: block
real :: x
x = 2.5
print *, x
end block other
print *, x
end program'''
    assert execute(source, capsys) == ['30', '20', '2.5', '10']


def test_block_arrays_use_entry_time_bounds(capsys):
    source = '''program blocks
integer :: n
do n = 1, 3
block
integer :: a(n)
a = n
print *, size(a), sum(a)
end block
end do
end program'''
    assert execute(source, capsys) == ['1', '1', '2', '4', '3', '9']


def test_block_in_procedure_preserves_dummy_and_keyword_names(capsys):
    source = '''program blocks
call show(10)
contains
subroutine show(x)
integer :: x
block
integer, parameter :: n = 2
integer :: x
character(len=n) :: text
x = 20
text = 'x'
print *, square(x=x), text
end block
print *, x
end subroutine
integer function square(x) result(y)
integer :: x
y = x*x
end function
end program'''
    assert execute(source, capsys) == ['400', 'x', '10']


def test_local_variable_does_not_rename_component_or_string(capsys):
    source = '''program blocks
type :: item
integer :: x
end type
type(item) :: obj
obj%x = 7
block
integer :: x
x = 20
print *, obj%x, x, 'x'
end block
end program'''
    assert execute(source, capsys) == ['7', '20', 'x']


def test_generated_names_do_not_collide_with_user_variables(capsys):
    source = '''program blocks
integer :: x, xf2p_block_3_x
x = 10
block
integer :: x
x = 20
xf2p_block_3_x = 7
print *, x
end block
print *, x, xf2p_block_3_x
end program'''
    assert execute(source, capsys) == ['20', '10', '7']


def test_operator_and_exponent_spelling_is_not_renamed(capsys):
    source = '''program blocks
block
integer :: d0
logical :: and
d0 = 2
and = .true.
if (and .and. .true.) print *, 1.0d0, d0
end block
end program'''
    assert execute(source, capsys) == ['1.0', '2']


def test_module_function_block_return_and_host_update(capsys):
    source = '''module m
integer :: count
contains
integer function f(x) result(y)
integer :: x
block
integer :: x
x = 20
count = count + 1
print *, count
end block
y = x
end function
end module
program blocks
use m
integer :: value
value = f(10)
print *, value
value = f(11)
print *, value
end program'''
    assert execute(source, capsys) == ['1', '10', '2', '11']


@pytest.mark.parametrize('declaration', ['integer, save :: x', 'integer :: x = 1', 'use iso_fortran_env'])
def test_unsupported_block_storage_or_import_is_rejected(declaration):
    with pytest.raises(ValueError, match='BLOCK'):
        basic_f2p().transpile(f'program p\nblock\n{declaration}\nend block\nend program')
