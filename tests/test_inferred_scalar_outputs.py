import ast

import pytest

from xf2p import basic_f2p


def run(source, capsys):
    generated = basic_f2p().transpile(source)
    exec(generated, {'__name__': '__main__'})
    return generated, capsys.readouterr().out.split()


def test_saved_counter_updates_dummy_without_intent(capsys):
    generated, output = run('''module m
integer, parameter :: n=100, step=5
contains
subroutine ini(data)
integer :: data
integer, save :: val=0
data=val+step
val=val+n-2*step
end subroutine
end module
program main
use m
integer :: i
call ini(i)
print *, i
call ini(i)
print *, i
end program''', capsys)
    assert output == ['5', '95']
    assert 'i = ini(i)' in generated


def test_forward_call_chain_and_keyword_arguments(capsys):
    generated, output = run('''module m
contains
subroutine outer(x, y)
integer :: x, y
call middle(y=y, x=x)
end subroutine
subroutine middle(x, y)
integer :: x, y
call inner(x, y)
end subroutine
subroutine inner(x, y)
integer :: x, y
x=x+1
y=y+2
end subroutine
end module
program main
use m
integer :: a, b
a=3
b=4
call outer(y=b, x=a)
print *, a, b
end program''', capsys)
    assert output == ['4', '6']
    assert 'a, b = outer(y=b, x=a)' in generated


def test_read_only_expression_is_not_copied_back(capsys):
    generated, output = run('''program main
call show(2+3)
contains
subroutine show(n)
integer :: n
print *, n
end subroutine
end program''', capsys)
    assert output == ['5']
    tree = ast.parse(generated)
    show = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'show')
    assert not any(isinstance(node, ast.Return) for node in ast.walk(show))


def test_early_return_syncs_save_and_returns_outputs(capsys):
    _, output = run('''program main
integer :: x
x=0
call update(x)
print *, x
call update(x)
print *, x
contains
subroutine update(x)
integer :: x
integer, save :: count=0
count=count+1
x=count
if (count > 0) return
x=-1
end subroutine
end program''', capsys)
    assert output == ['1', '2']


def test_omitted_optional_output_does_not_drop_present_outputs(capsys):
    _, output = run('''program main
integer :: x, y
x=0
y=0
call update(x)
print *, x
call update(x, y)
print *, x, y
contains
subroutine update(x, extra)
integer :: x
integer, optional :: extra
x=x+1
if (present(extra)) extra=9
end subroutine
end program''', capsys)
    assert output == ['1', '2', '9']


def test_elements_components_and_explicit_outputs_keep_order(capsys):
    _, output = run('''program main
type :: holder
integer :: n
end type
type(holder) :: h
integer :: a(2)
a=0
h%n=0
call update(a(2), h%n)
print *, a, h%n
contains
subroutine update(x, y)
integer :: x
integer, intent(out) :: y
x=12
y=34
end subroutine
end program''', capsys)
    assert output == ['0', '12', '34']


def test_read_defines_scalar_dummy(capsys):
    _, output = run('''program main
integer :: n
n=0
call parse(n)
print *, n
contains
subroutine parse(n)
integer :: n
character(len=4) :: record='1234'
read(record, '(i4)') n
end subroutine
end program''', capsys)
    assert output == ['1234']


def test_nondefinable_modified_actual_is_diagnosed():
    with pytest.raises(ValueError, match='definable actual'):
        basic_f2p().transpile('''program main
call update(3)
contains
subroutine update(x)
integer :: x
x=4
end subroutine
end program''')


def test_external_write_unit_is_read_only():
    generated = basic_f2p().transpile('''program main
call show(6)
contains
subroutine show(unit)
integer :: unit
write(unit, *) 5
end subroutine
end program''')
    assert 'return unit' not in generated



def test_scalar_types_without_intent(capsys):
    _, output = run('''program main
real :: x
logical :: flag
character(len=5) :: text
x=1.0
flag=.false.
text='old'
call update(x, flag, text)
print *, x, flag, trim(text), len(text)
contains
subroutine update(x, flag, text)
real :: x
logical :: flag
character(len=*) :: text
x=x+0.5
flag=.true.
text='new'
end subroutine
end program''', capsys)
    assert output == ['1.5', 'True', 'new', '5']
