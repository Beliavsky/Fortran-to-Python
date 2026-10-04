program matrix_operations
   implicit none
   real(kind=kind(1d0)) :: a(2,2), b(2,2), c(2,2), v(2), w(2)
   integer :: i, j
   a = reshape([1d0, 2d0, 3d0, 4d0], [2,2])
   b = transpose(a)
   c = matmul(a,b)
   v = [2d0, -1d0]
   w = matmul(a,v)
   do j = 1, 2
      do i = 1, 2
         print *, c(i,j)
      end do
   end do
   print *, w(1), w(2), dot_product(v,v)
end program matrix_operations
