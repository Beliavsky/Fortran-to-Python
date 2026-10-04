program array_sections
   implicit none
   integer :: a(6), i
   do i = 1, 6
      a(i) = i * 2
   end do
   a(2:6:2) = a(1:5:2) + 1
   do i = 1, 6
      print *, a(i)
   end do
   print *, sum(a), minval(a), maxval(a), size(a)
end program array_sections
