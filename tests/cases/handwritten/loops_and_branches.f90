program loops_and_branches
   implicit none
   integer :: i, total, n
   total = 0
   do i = 1, 6
      if (mod(i, 2) == 0) cycle
      total = total + i
   end do
   n = 3
   do while (n > 0)
      total = total + n
      n = n - 1
   end do
   print *, total, n
end program loops_and_branches
