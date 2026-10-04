program explicit_save
   implicit none
   integer :: i
   do i = 1,3
      print *, next_value()
   end do
contains
   integer function next_value()
      integer :: counter = 0
      save counter
      counter = counter + 1
      next_value = counter
   end function next_value
end program explicit_save
