program allocation
   implicit none
   real(kind=kind(1d0)), allocatable :: a(:)
   integer :: i
   allocate(a(3))
   do i = 1, size(a)
      a(i) = real(i, kind(1d0)) / 2d0
   end do
   print *, size(a), sum(a)
   deallocate(a)
end program allocation
