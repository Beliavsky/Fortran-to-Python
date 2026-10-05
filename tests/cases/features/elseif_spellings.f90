program elseif_spellings
   implicit none
   integer :: i
   do i = 1, 10
      if (mod(i, 2) == 0) then
         print *, i, i**2
      elseif (i > 3) then
         print *, i, i**3
      endif
   enddo
   print *, 'done'
end program elseif_spellings
