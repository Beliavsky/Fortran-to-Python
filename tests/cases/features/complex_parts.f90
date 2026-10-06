program main
implicit none
type :: box
real :: re, im
complex :: z, a(2)
end type
type(box) :: b, records(2)
complex :: s, a(4), m(2,2)
complex(kind=8) :: wide
complex, target :: target
complex, pointer :: p
s = (1.0,2.0)
s%re = 3.0
s%im = 4.0
print *, s%re, s%im
a = (1.0,2.0)
a%re = 3.0
a(2:4:2)%im = [7.0,8.0]
a(1)%re = 9.0
print *, a%re
print *, a%im
where (a%re > 3.0)
a%im = 10.0
end where
print *, a%im
m = (1.0,2.0)
m(:,2)%re = [11.0,12.0]
m(2,1)%im = 13.0
print *, m%re
print *, m%im
b%re = 21.0
b%im = 22.0
b%z = (5.0,6.0)
b%z%im = 14.0
b%a = [(1.0,2.0),(1.0,2.0)]
b%a(2)%re = 15.0
print *, b%re, b%im, b%z%re, b%z%im, b%a%re
records%re = 31.0
records%im = 32.0
records(1)%z = (3.0,4.0)
records(1)%z%re = 33.0
records(2)%z = (5.0,6.0)
print *, records%re, records%im, records%z%re
call update(s)
print *, s%re, s%im
target = (1.0,2.0)
p => target
p%im = 44.0
print *, target%re, target%im
wide = (1.0d0,2.0d0)
print *, kind(s%re), kind(wide%im), kind(records%z%re)
print *, 'z.re z.im'
contains
subroutine update(z)
complex :: z
z%re = 41.0
end subroutine
end program
