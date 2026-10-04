program integer_assignment_conversions
   implicit none
   integer :: scalar, a(4), b(2,2), i, j
   real(kind=kind(1d0)) :: values(4)
   logical :: mask(4)
   values = [1.9d0, -1.9d0, 2.8d0, -2.8d0]
   scalar = -3.9d0
   a = values
   do i = 1, 4
      print *, a(i)
   end do
   a(2:3) = [-4.9d0, 4.9d0]
   a(1) = -7.9d0
   mask = a > 0
   where (mask)
      a = values * 2d0
   end where
   b = 3.9d0
   b(1,2) = -5.9d0
   b(:,1) = [6.9d0, -6.9d0]
   print *, scalar
   do i = 1, 4
      print *, a(i)
   end do
   do j = 1, 2
      do i = 1, 2
         print *, b(i,j)
      end do
   end do
end program integer_assignment_conversions
