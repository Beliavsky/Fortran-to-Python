import pytest

from xf2p import basic_f2p


@pytest.mark.parametrize('value_attrs', ['value', 'optional, value'])
def test_scalar_value_in_functions_and_subroutines(value_attrs, capsys):
    source = f'''module m
contains
integer function f(i) result(r)
integer, {value_attrs} :: i
i=i*10
r=i
end function
subroutine sub(i)
integer, {value_attrs} :: i
i=i*10
print *, i
end subroutine
end module
program main
use m
integer :: i,j
i=3
j=f(i)
print *, i,j
call sub(i)
print *, i
j=f(4)
call sub(5)
print *, j
end program'''
    generated = basic_f2p().transpile(source)
    exec(generated, {'__name__': '__main__'})
    assert capsys.readouterr().out.split() == ['3', '30', '30', '3', '50', '40']
    assert 'i = sub(' not in generated


def test_mixed_value_and_reference_dummies(capsys):
    source = '''program main
integer :: i,j,k
i=3
j=4
k=f(i,j)
print *, i,j,k
call sub(i,j)
print *, i,j
contains
integer function f(a,b) result(r)
integer, value :: a
integer :: b
a=a*10
b=b*10
r=a+b
end function
subroutine sub(a,b)
integer, value :: a
integer, intent(inout) :: b
a=a*10
b=b+1
end subroutine
end program'''
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.split() == ['3', '40', '70', '3', '41']


def test_derived_type_value_copies_components(capsys):
    source = '''module m
type :: box
integer :: n
end type
contains
integer function f(a) result(r)
type(box), value :: a
a%n=a%n*10
r=a%n
end function
subroutine sub(a)
type(box), value :: a
a%n=99
end subroutine
end module
program main
use m
type(box) :: a
integer :: j
a%n=3
j=f(a)
call sub(a)
print *, a%n,j
end program'''
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.split() == ['3', '30']
