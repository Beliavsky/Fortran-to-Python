module impure_elemental_subroutines_mod
implicit none
integer :: calls = 0
contains
impure elemental subroutine clamp_nonnegative(x)
real(kind=kind(1d0)), intent(inout) :: x
calls = calls + 1
if (x < 0d0) x = 0d0
end subroutine
impure elemental subroutine print_sqrt(i)
integer, intent(in) :: i
print *, i, sqrt(real(i, kind=kind(1d0)))
end subroutine
elemental subroutine fill(x)
integer, intent(out) :: x
x = 7
end subroutine
end module
program test
use impure_elemental_subroutines_mod
implicit none
real(kind=kind(1d0)) :: x(4), scalar
integer :: y(3), empty(0)
x = [-2d0,-1d0,1d0,2d0]
call clamp_nonnegative(x)
print *, x, calls
scalar = -3d0
call clamp_nonnegative(scalar)
print *, scalar, calls
call print_sqrt([2,4,6,8,10,12,14,16])
call print_sqrt(empty)
call fill(y)
print *, y
x = [-3d0,-2d0,-1d0,4d0]
call clamp_nonnegative(x(1:4:2))
print *, x, calls
end program
