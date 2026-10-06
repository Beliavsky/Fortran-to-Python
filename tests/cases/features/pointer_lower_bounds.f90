program main
implicit none
type :: box
integer, pointer :: p(:) => null()
end type
type(box) :: b(2)
integer, target :: a(-2:3), m(2,3)
integer, pointer :: p(:), q(:), mat(:,:)
a = [10,20,30,40,50,60]
p(0:) => a
q(-3:) => a
print *, lbound(p), ubound(p), lbound(q), ubound(q), lbound(a), ubound(a)
p(1) = 200
print *, a(-1), q(-2), associated(p, q)
p(-1:) => a(-1:3:2)
print *, lbound(p), ubound(p), p(-1), p(0), p(1)
p(0) = 400
print *, a(1), associated(p, a(-1:3:2))
q => p
print *, lbound(q), ubound(q), q(0)
p => a
print *, lbound(p), ubound(p), p(-2), lbound(q), q(0)
p => a(:)
print *, lbound(p), ubound(p), p(1)
call set_section(p, a)
print *, lbound(p), ubound(p), p(0), p(2)
p(0) = 99
print *, a(-1)
b(1)%p(0:) => a(-1:1)
b(2)%p(-2:) => a(-1:1)
b(1)%p(1) = 88
print *, lbound(b(1)%p), ubound(b(1)%p), lbound(b(2)%p), b(2)%p(-1), a(0)
m = reshape([1,2,3,4,5,6], [2,3])
mat(-1:,0:) => m
print *, lbound(mat), ubound(mat), mat(-1,0), mat(0,2)
mat(0,1) = 77
print *, m(2,2), associated(mat, m)
p(0:) => a(3:-2:-2)
print *, lbound(p), ubound(p), p(0), p(1), p(2)
p(0:) => a(1:0)
print *, associated(p), lbound(p), ubound(p), associated(p, a(1:0))
contains
subroutine set_section(x, a)
integer, pointer, intent(out) :: x(:)
integer, target, intent(inout) :: a(:)
x(0:) => a(2:4)
end subroutine
end program
