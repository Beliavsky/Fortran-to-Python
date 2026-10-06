program optional_allocatable
implicit none
integer, allocatable :: a(:)
integer :: result
call relay()
call relay(a)
a=[4,5]
call relay(a)
print *, inspect(), inspect(a)
call clear(a)
print *, allocated(a), inspect(a)
result=populate(a)
print *, result, allocated(a), a
call reset()
call reset(a)
print *, allocated(a)
contains
subroutine relay(v)
integer, allocatable, optional, intent(inout) :: v(:)
call show(v)
print *, present(v)
end subroutine
subroutine show(w)
integer, allocatable, optional, intent(in) :: w(:)
print *, present(w)
if (present(w)) print *, allocated(w)
end subroutine
integer function inspect(v) result(r)
integer, allocatable, optional, intent(in) :: v(:)
r=-1
if (present(v)) then
r=0
if (allocated(v)) r=size(v)
end if
end function
integer function populate(v) result(r)
integer, allocatable, optional, intent(inout) :: v(:)
r=0
if (present(v)) then
v=[7,8,9]
print *, present(v), allocated(v)
r=size(v)
end if
end function
subroutine clear(v)
integer, allocatable, optional, intent(inout) :: v(:)
deallocate(v)
print *, present(v), allocated(v)
end subroutine
subroutine reset(v)
integer, allocatable, optional, intent(out) :: v(:)
call show(v)
print *, present(v)
end subroutine
end program
