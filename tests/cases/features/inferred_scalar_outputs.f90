module inferred_scalar_outputs_mod
implicit none
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
subroutine counter(x)
integer :: x
integer, save :: count=0
count=count+1
x=count
if (count > 0) return
x=-1
end subroutine
subroutine optional_update(x, y)
integer :: x
integer, optional :: y
x=x+1
if (present(y)) y=9
end subroutine
subroutine update_types(x, flag, text)
real :: x
logical :: flag
character(len=*) :: text
x=x+0.5
flag=.true.
text='new'
end subroutine
end module
program inferred_scalar_outputs
use inferred_scalar_outputs_mod
implicit none
integer :: a, b
real :: x
logical :: flag
character(len=5) :: text
a=3
b=4
call outer(y=b, x=a)
print *, a, b
call counter(a)
print *, a
call counter(a)
print *, a
call optional_update(a)
print *, a
call optional_update(a, b)
print *, a, b
x=1.0
flag=.false.
text='old'
call update_types(x, flag, text)
print *, x, flag, trim(text), len(text)
end program
