program labeled_format
   implicit none
   integer :: i
   do i = 1,2
      write(*,100) i, real(i,kind(1d0))/2d0
   end do
100 format(i3,1x,f8.3)
end program labeled_format
