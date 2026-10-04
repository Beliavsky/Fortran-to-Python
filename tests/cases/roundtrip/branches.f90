! transpiled by xp2f.py from branches.py on 2026-10-04 10:46:44
program branches
   implicit none
   integer, parameter :: value = 12 ! constant from python source
   integer :: result
   
   if (value > 10) then
      result = value * 2
   else
      result = value - 1
   end if
   print *, result
end program branches
