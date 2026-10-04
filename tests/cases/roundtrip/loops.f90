! transpiled by xp2f.py from loops.py on 2026-10-04 10:46:33
program loops
   implicit none
   integer :: i, total
   
   total = 0
   do i = 1, 6
      if (modulo(i, 2) /= 0) total = total + i
   end do
   print *, total
end program loops
