module function_scalar_outputs_mod
implicit none
contains
integer function outer(i) result(r)
integer :: i
r=f(i)
end function
integer function f(i) result(r)
integer :: i
i=i*10
r=i
return
end function
integer function advance(i) result(r)
integer :: i
i=i+1
r=i
end function
end module
program function_scalar_outputs
use function_scalar_outputs_mod
implicit none
integer :: i, j, a(2)
i=3
j=f(i)
print *, i,j
i=2
j=abs(outer(i=i))+1
print *, i,j
a=[2,3]
j=f(a(2))
print *, a,j
i=0
do while (advance(i)<3)
end do
print *, i
end program
