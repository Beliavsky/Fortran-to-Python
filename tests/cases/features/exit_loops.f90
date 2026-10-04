program exit_loops
   implicit none
   integer :: i, total
   total = 0
   do i = 1,10
      if (i == 4) exit
      total = total + i
   end do
   print *, total, i
end program exit_loops
