! transpiled by xp2f.py from arithmetic.py on 2026-10-04 10:48:41
program arithmetic
   implicit none
   integer, parameter :: a = 7 ! constant from python source
   integer, parameter :: b = 3 ! constant from python source
   
   print *, a + b, a - b, a * b
   print *, a ** 2, b ** 3
end program arithmetic
