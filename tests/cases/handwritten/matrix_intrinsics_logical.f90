program matrix_intrinsics_logical
   implicit none
   logical :: a(2,3), b(3,2), c(2,2), t(3,2), v(3), left(2), right(2)
   integer :: i, j
   a = .false.
   b = .false.
   a(1,1) = .true.
   a(2,3) = .true.
   b(1,2) = .true.
   b(3,1) = .true.
   v = [.true., .false., .true.]
   t = transpose(a)
   c = matmul(a,b)
   left = matmul(v,b)
   right = matmul(a,v)
   do j = 1, 2
      do i = 1, 2
         print *, merge(1,0,c(i,j))
      end do
   end do
   print *, count(t), count(left), count(right)
   print *, merge(1,0,dot_product(v,v))
   v = .false.
   print *, merge(1,0,dot_product(v,v))
end program matrix_intrinsics_logical
