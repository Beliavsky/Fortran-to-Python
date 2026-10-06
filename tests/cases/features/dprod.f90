module dispatch
interface choose
module procedure single_value, double_value
end interface
contains
integer function single_value(x)
real, intent(in) :: x
single_value = 4
end function
integer function double_value(x)
double precision, intent(in) :: x
double_value = 8
end function
end module
program main
use dispatch
implicit none
real :: a(3), b(3), m(2,2), x
double precision :: z(3), matrix(2,2), exact
print *, dprod(2.0,3.0), dprod(y=3.0,x=2.0)
a = [1.0,-2.0,0.5]
b = [3.0,4.0,-2.0]
z = dprod(a,b)
print *, z
print *, dprod(a,2.0), dprod(2.0,a)
m = reshape([1.0,2.0,3.0,4.0], [2,2])
matrix = dprod(m,m)
print *, matrix
x = 1.0 + 2.0**(-23)
exact = (1.0d0 + 2.0d0**(-23))**2
print *, dprod(x,x) == exact
print *, kind(dprod(x,x)), choose(dprod(x,x))
print *, 'dprod(2.0,3.0)'
end program
