program floating_intrinsics
use iso_fortran_env, only: real64
implicit none
real(real64) :: x(5), directions(5), zero, subnormal
x = [0d0, 1d0, -1d0, 0.7d0, 8d0]
directions = [1d0, -1d0, 1d0, -1d0, 1d0]
zero = 0d0
subnormal = nearest(zero, 1d0)
print *, fraction(x), exponent(x)
print *, scale(fraction(x), exponent(x))
print *, set_exponent(x, 3)
print *, spacing(x), rrspacing(x)
print *, merge(1, 0, spacing(zero) == tiny(zero))
print *, merge(1, 0, spacing(subnormal) == tiny(zero))
print *, merge(1, 0, nearest(zero,-1d0) == -subnormal)
print *, merge(1, 0, nearest(1d0,-1d0) == 1d0-epsilon(1d0)/2d0)
print *, nearest(x, directions)
print *, dim(x, 1d0), sign(x, directions)
print *, digits(x), precision(x), range(x), radix(x)
print *, asin([0d0,0.5d0]), atan([0d0,1d0]), atan(1d0, -1d0)
print *, atan2([1d0,-1d0],[-1d0,-1d0])
print *, 'fraction(x) exponent(x) scale(x,3) set_exponent(x,3)'
print *, 'spacing(x) rrspacing(x) nearest(x,1) tiny(x) huge(x)'
end program
