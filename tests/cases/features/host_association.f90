module host_module
implicit none
integer :: calls = 0
contains
subroutine outer(total)
integer, intent(inout) :: total
call inner()
contains
subroutine inner()
total = total + 2
calls = calls + 1
end subroutine inner
end subroutine outer
end module host_module

program host_association
use host_module
implicit none
integer :: count, value
real(8) :: weights(0:1)
character(len=4) :: label
count = 0
value = 5
weights = [1d0, 2d0]
label = 'old'
call tick()
call tick()
value = next_value()
call shadow()
call outer(value)
print *, count, value, calls, weights
print *, label
contains
subroutine tick()
count = count + 1
weights(0) = weights(0) + 0.5d0
label = 'new'
end subroutine tick
integer function next_value()
count = count + 1
next_value = value + count
end function next_value
subroutine shadow()
integer :: count
count = 99
print *, count
end subroutine shadow
end program host_association
