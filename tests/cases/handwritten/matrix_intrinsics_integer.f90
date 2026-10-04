program matrix_intrinsics_integer
   implicit none
   integer :: a(2,3), b(3,2), c(2,2), t(3,2), v(3), left(2), right(2), i, j
   a = reshape([1,2,3,4,5,6], [2,3])
   t = transpose(matrix=a)
   b = t
   c = matmul(matrix_b=b, matrix_a=a)
   v = [2,-1,3]
   left = matmul(v,b)
   right = matmul(a,v)
   do j = 1, 2
      do i = 1, 2
         print *, c(i,j)
      end do
   end do
   print *, left(1), left(2), right(1), right(2)
   print *, dot_product(vector_b=v, vector_a=v)
   print *, sum(transpose(a)), t(3,2)
   a = reshape([1,2], [2,3], pad=[9,8])
   print *, a(1,1), a(2,1), a(1,2), a(2,3)
   a = reshape(order=[2,1], shape=[2,3], source=[1,2,3,4,5,6])
   print *, a(1,2), a(2,1)
end program matrix_intrinsics_integer
