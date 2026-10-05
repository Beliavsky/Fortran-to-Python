module value_arguments_mod
implicit none
type :: box
integer :: n
end type
contains
integer function f(i) result(r)
integer, value :: i
i=i*10
r=i
end function
subroutine sub(i)
integer, value :: i
i=i*10
print *, 'in sub, i=', i
end subroutine
integer function mixed(a,b) result(r)
integer, value :: a
integer :: b
a=a*10
b=b*10
r=a+b
end function
subroutine change_box(a)
type(box), value :: a
a%n=99
end subroutine
end module
program value_arguments
use value_arguments_mod
implicit none
integer :: i,j,k
type(box) :: a
i=3
j=f(i)
print *, i,j
call sub(i)
print *, 'after sub, i=', i
j=f(4)
call sub(5)
print *, j
j=4
k=mixed(i,j)
print *, i,j,k
a%n=3
call change_box(a)
print *, a%n
end program
