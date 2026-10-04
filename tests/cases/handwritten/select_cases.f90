program select_cases
   implicit none
   integer :: i, score
   score = 0
   do i = 0, 4
      select case (i)
      case (0)
         score = score + 1
      case (1:3)
         score = score + 10
      case default
         score = score + 100
      end select
   end do
   print *, score
end program select_cases
