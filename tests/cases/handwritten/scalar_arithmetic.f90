program scalar_arithmetic
   implicit none
   integer :: i, j
   real(kind=kind(1d0)) :: x
   i = 7
   j = -7
   x = 2.5d0
   print *, i / 3, j / 3, mod(j, 3), modulo(j, 3)
   print *, x * 4d0, sqrt(9d0), int(x), real(i, kind(1d0))
end program scalar_arithmetic
