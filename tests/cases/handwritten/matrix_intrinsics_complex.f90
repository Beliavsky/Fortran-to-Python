program matrix_intrinsics_complex
   implicit none
   complex(kind=kind(1d0)) :: a(2,2), t(2,2), c(2,2), u(2), v(2), z
   integer :: i, j
   a(1,1) = cmplx(1d0,2d0,kind=kind(1d0))
   a(2,1) = cmplx(3d0,-1d0,kind=kind(1d0))
   a(1,2) = cmplx(-2d0,1d0,kind=kind(1d0))
   a(2,2) = cmplx(4d0,3d0,kind=kind(1d0))
   t = transpose(a)
   c = matmul(a,t)
   u = a(:,1)
   v = a(:,2)
   z = dot_product(u,v)
   print *, real(z), aimag(z)
   print *, real(t(1,2)), aimag(t(1,2))
   do j = 1, 2
      do i = 1, 2
         print *, real(c(i,j)), aimag(c(i,j))
      end do
   end do
end program matrix_intrinsics_complex
