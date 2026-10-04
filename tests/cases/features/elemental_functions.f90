program elemental_functions
   implicit none
   real(kind=kind(1d0)) :: x(3), y(3)
   integer :: i
   x = [1d0,-2d0,3d0]
   y = affine(x,2d0)
   print *, affine(4d0,3d0)
   do i = 1,3
      print *, y(i)
   end do
contains
   elemental function affine(value,scale) result(result_value)
      real(kind=kind(1d0)), intent(in) :: value,scale
      real(kind=kind(1d0)) :: result_value
      result_value = value * scale + 1d0
   end function affine
end program elemental_functions
