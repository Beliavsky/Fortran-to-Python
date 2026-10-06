program allocatable_bounds
implicit none
integer, allocatable :: a(:), b(:), m(:,:), empty(:,:)
allocate(a(-2:2))
a=[10,20,30,40,50]
call vector(a)
call ordinary(a)
call rebased(a)
call clones(a)
call replace(a)
print *, lbound(a), ubound(a), a(-4), a(-2)
call transfer(a,b)
print *, allocated(a), lbound(b), ubound(b), b(-4)
b=[1,2,3]
print *, lbound(b), ubound(b)
b=[7,8]
print *, lbound(b), ubound(b)
call make(a)
print *, lbound(a), ubound(a), a(0), a(1)
allocate(m(0:1,-1:1))
m=reshape([1,2,3,4,5,6],[2,3])
call matrix(m)
allocate(empty(-2:-3,4:6))
call matrix(empty)
call saved_step()
call saved_step()
contains
subroutine vector(x)
integer, allocatable, intent(in) :: x(:)
print *, lbound(x), ubound(x), x(-2), x(0), x(2)
print *, x(-1:1)
end subroutine
subroutine ordinary(x)
integer, intent(in) :: x(:)
integer, allocatable :: copy(:)
print *, lbound(x), ubound(x), x(1), x(5)
copy=x
print *, lbound(copy), ubound(copy)
end subroutine
subroutine rebased(x)
integer, intent(in) :: x(0:)
integer, allocatable :: copy(:)
print *, lbound(x), ubound(x), x(0), x(4)
copy=x
print *, lbound(copy), ubound(copy)
end subroutine
subroutine clones(x)
integer, allocatable, intent(in) :: x(:)
integer, allocatable :: source_copy(:), mold_copy(:), assignment_copy(:)
allocate(source_copy,source=x)
allocate(mold_copy,mold=x)
mold_copy=8
assignment_copy=x
print *, lbound(source_copy), ubound(source_copy), source_copy(-2)
print *, lbound(mold_copy), ubound(mold_copy), mold_copy(-2)
print *, lbound(assignment_copy), ubound(assignment_copy), assignment_copy(-2)
end subroutine
subroutine replace(x)
integer, allocatable, intent(inout) :: x(:)
deallocate(x)
allocate(x(-4:-2))
x=[1,2,3]
end subroutine
subroutine transfer(x,y)
integer, allocatable, intent(inout) :: x(:),y(:)
call move_alloc(x,y)
print *, allocated(x), lbound(y), ubound(y), y(-2)
end subroutine
subroutine make(x)
integer, allocatable, intent(out) :: x(:)
allocate(x(0:1))
x=[4,5]
end subroutine
subroutine matrix(x)
integer, allocatable, intent(in) :: x(:,:)
integer :: d
print *, lbound(x), ubound(x), size(x)
do d=1,2
print *, lbound(x,dim=d), ubound(x,dim=d)
end do
if (size(x)>0) print *, x(0,-1), x(1,1)
end subroutine
subroutine saved_step()
integer, allocatable, save :: x(:)
if (.not. allocated(x)) then
allocate(x(-2:0))
x=5
end if
x(-2)=x(-2)+1
print *, lbound(x), ubound(x), x(-2)
end subroutine
end program
