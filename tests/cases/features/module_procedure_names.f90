module strings_mod
implicit none
contains
integer function helper(i)
integer, intent(in) :: i
helper=i+100
end function
end module
module m
implicit none
contains
integer function used(i)
integer, intent(in) :: i
used=helper(i)
end function
integer function helper(i)
integer, intent(in) :: i
helper=i+1
end function
end module
program main
use strings_mod, only: helper
use m, only: used, second=>helper
implicit none
print *, used(2), helper(2), second(2)
end program
