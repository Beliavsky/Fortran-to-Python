program main
implicit none
integer, target :: a(5), b(5), x, y
integer, target :: m(2,3)
integer, pointer :: p(:), q(:), r
a = [1, 2, 3, 4, 5]
b = a
x = 99
y = 99
nullify(p, q, r)
print *, associated(p), associated(p, a), associated(r, x)
p => a
q => a
r => x
print *, associated(p), associated(p, a), associated(p, b)
print *, associated(p, q), associated(r, x), associated(r, y)
q => b
print *, associated(p, q), associated(q, b)
p => a(2:4)
print *, associated(p, a), associated(p, a(2:4)), associated(p, a(1:3))
q => a(2:4)
print *, associated(p, q)
p => a(1:5:2)
print *, associated(p, a(1:5:2)), associated(p, a(1:3))
r => a(3)
print *, associated(r, a(3)), associated(r, a(2))
r = 77
print *, a(3)
print *, associated(target=a(3), pointer=r)
nullify(p, r)
print *, associated(p), associated(p, q), associated(r, a(3))
m = reshape([1,2,3,4,5,6], [2,3])
p => m(2,:)
r => m(2,3)
print *, associated(p, m(2,:)), associated(p, m(1,:))
print *, associated(r, m(2,3)), associated(r, m(1,3))
r = 88
print *, m(2,3)
end program
