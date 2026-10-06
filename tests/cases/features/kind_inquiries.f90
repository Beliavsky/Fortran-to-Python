module kind_checks
use iso_fortran_env, only: real32, real64
implicit none
integer :: counter = 0
contains
real(real64) function value()
counter = counter + 1
value = 2.0d0
end function
elemental function twice(x) result(y)
real(real64), intent(in) :: x
real(real64) :: y
y = 2*x
end function
end module
program main
use kind_checks
implicit none
integer, parameter :: dp = kind(1.0d0)
real(real32) :: single
real(dp) :: double, a(2,2), v(2)
real(dp), allocatable :: unallocated(:)
complex(4) :: z4
complex(8) :: z8
complex(16) :: z16
integer(1) :: i1
integer(8) :: i8
logical(1) :: b1
logical(8) :: b8
character(len=3) :: text
print *, kind(1), kind(1_8), kind(1.0), kind(1.0d0), kind(1.0_real64)
print *, kind(single), kind(double), kind(a), kind(a(1,1)), kind(a(:,1))
print *, kind(z4), kind(z8), kind(z16), kind(i1), kind(i8)
print *, kind(b1), kind(b8), kind(.true.), kind(.false._1), kind(text), kind('abc')
print *, kind(single + double), kind(double + i8), kind(single ** i8)
print *, kind(matmul(a,v)), kind(dot_product(v,v)), kind(sum(v)), kind(transpose(a))
print *, kind(real(i8,kind=dp)), kind(int(double,kind=8)), kind(cmplx(single,kind=8))
print *, kind(value()), counter, kind(twice(v)), kind(unallocated)
print *, kind((1.0,2.0)), kind((1.0d0,2.0d0)), kind(kind(double)), kind(x=double)
end program
