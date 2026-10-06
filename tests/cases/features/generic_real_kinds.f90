module generic_kinds
use iso_fortran_env, only: real32, real64
implicit none
interface identify
   module procedure scalar32, scalar64, vector32, vector64, matrix64
end interface
contains
subroutine scalar32(x)
real(real32), intent(in) :: x
print *, 'scalar32'
end subroutine
subroutine scalar64(x)
real(kind=real64), intent(in) :: x
print *, 'scalar64'
end subroutine
subroutine vector32(x)
real(real32), intent(in) :: x(:)
print *, 'vector32'
end subroutine
subroutine vector64(x)
real(real64), intent(in) :: x(:)
print *, 'vector64'
end subroutine
subroutine matrix64(x)
real(real64), intent(in) :: x(:,:)
print *, 'matrix64'
end subroutine
real(real64) function value64()
value64 = 1.0_real64
end function
end module
program main
use generic_kinds
implicit none
real(real32) :: single = 1.0
real(real64) :: double = 1.0d0, v(2) = [1.0d0, 2.0d0], a(1,2)
a = 1.0d0
call identify(1.0)
call identify(1.0d0)
call identify(1.0_real64)
call identify(single)
call identify(double)
call identify(single + 2.0)
call identify(single + double)
call identify(x=double)
call identify([1.0, 2.0])
call identify(v)
call identify(a)
call identify(v(1))
call identify(v(1:2))
call identify(value64())
end program
