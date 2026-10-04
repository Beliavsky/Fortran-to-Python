program do_concurrent
   implicit none
   integer :: i, a(5)
   do concurrent (i=1:5)
      a(i) = i*i
   end do
   do i = 1,5
      print *, a(i)
   end do
end program do_concurrent
