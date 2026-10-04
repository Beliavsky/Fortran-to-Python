program strided_sections
   implicit none
   integer :: a(0:5), b(6), m(-1:1,2:5), step, i, j
   logical :: mask(6), short_mask(3)
   do i = 0, 5
      a(i) = i + 10
   end do
   print *, sum(a(::-1)), sum(a(5:0:-2)), sum(a(:0:-2))
   print *, sum(a(0:5:2)), size(a(0:5:-1)), size(a(5:0:1))
   print *, sum(a(size(a(:))-1:0:-2))
   b = a(5:0:-1)
   do i = 1, 6
      print *, b(i)
   end do
   step = -2
   b(6:1:step) = [21,22,23]
   print *, b(6), b(4), b(2)
   b(:) = 0
   b(::2) = a(0:4:2)
   if (b(1) == 10) b(::2) = b(::2) + 1
   short_mask = [.true., .false., .true.]
   where (short_mask)
      b(::2) = b(::2) + 2
   end where
   mask = b == 0
   where (mask)
      b = -1
   end where
   print *, sum(b)
   do j = 2, 5
      do i = -1, 1
         m(i,j) = i + 10*j
      end do
   end do
   print *, sum(m(1:-1:-1,5:2:-2)), sum(m(-1:1:2,::2))
   m(1:-1:-1,5:2:-2) = -7
   print *, sum(m)
   a(5:0:-1) = a(:)
   do i = 0, 5
      print *, a(i)
   end do
end program strided_sections
