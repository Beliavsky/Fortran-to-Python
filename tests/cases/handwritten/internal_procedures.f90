program internal_procedures
   implicit none
   real(kind=kind(1d0)) :: x
   x = square(3d0)
   call increment(x)
   print *, x
contains
   pure function square(a) result(b)
      real(kind=kind(1d0)), intent(in) :: a
      real(kind=kind(1d0)) :: b
      b = a * a
   end function square
   subroutine increment(a)
      real(kind=kind(1d0)), intent(inout) :: a
      a = a + 1d0
   end subroutine increment
end program internal_procedures
