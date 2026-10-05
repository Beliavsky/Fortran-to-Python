module allocatable_out_mod
implicit none
contains
subroutine discard(v)
integer, intent(out), allocatable :: v(:)
print *, allocated(v)
return
end subroutine
subroutine replace(v)
integer, allocatable, intent(out) :: v(:)
print *, allocated(v)
allocate(v(2))
v=[4,5]
end subroutine
subroutine retain(v)
integer, allocatable, intent(inout) :: v(:)
print *, allocated(v)
v(1)=7
end subroutine
integer function scalar_out(v) result(r)
integer, allocatable, intent(out) :: v
print *, allocated(v)
r=9
end function
subroutine text_out(v)
character(len=:), allocatable, intent(out) :: v
print *, allocated(v)
v='newer'
end subroutine
subroutine optional_out(v)
integer, allocatable, optional, intent(out) :: v(:)
print *, present(v)
if (present(v)) then
print *, allocated(v)
v=[4,5]
end if
end subroutine
end module
program allocatable_out
use allocatable_out_mod
implicit none
integer, allocatable :: w(:), scalar
integer :: n
character(len=:), allocatable :: text
w=[10,20,30]
call discard(w)
print *, allocated(w)
w=[10,20,30]
call replace(w)
print *, allocated(w), size(w), w
call retain(w)
print *, allocated(w), w
allocate(scalar)
scalar=3
n=scalar_out(scalar)
print *, n, allocated(scalar)
text='old'
call text_out(text)
print *, allocated(text), len(text), text
deallocate(w)
call optional_out(w)
print *, allocated(w), w
call optional_out(w)
print *, allocated(w), w
call optional_out()
end program
