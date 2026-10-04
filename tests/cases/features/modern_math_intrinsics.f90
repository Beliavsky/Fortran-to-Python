program test_modern_math_intrinsics
   use iso_fortran_env, only : real64
   implicit none

   integer, parameter :: dp = real64

   real(dp) :: x
   real(dp) :: y
   real(dp) :: a
   real(dp) :: b
   real(dp) :: c
   integer :: n

   x = 0.7_dp
   y = 1.3_dp
   a = 30.0_dp
   b = 0.5_dp
   c = 2.0_dp
   n = 3

   print *, "Modern Fortran mathematical intrinsics"
   print *, "======================================"
   print *

   !---------------------------------------------------------------
   ! Basic transcendental functions
   !---------------------------------------------------------------

   print *, "Basic functions"
   print *, "---------------"
   print *, "sqrt(x)       = ", sqrt(x)
   print *, "exp(x)        = ", exp(x)
   print *, "log(x)        = ", log(x)
   print *, "log10(x)      = ", log10(x)
   print *

   !---------------------------------------------------------------
   ! Trigonometric functions, radians
   !---------------------------------------------------------------

   print *, "Trigonometric functions (radians)"
   print *, "---------------------------------"
   print *, "sin(x)        = ", sin(x)
   print *, "cos(x)        = ", cos(x)
   print *, "tan(x)        = ", tan(x)
   print *, "asin(x)       = ", asin(x)
   print *, "acos(x)       = ", acos(x)
   print *, "atan(x)       = ", atan(x)
   print *, "atan2(y,x)    = ", atan2(y, x)
   print *

   !---------------------------------------------------------------
   ! Trigonometric functions using degrees
   !
   ! SIND, COSD, TAND, ASIND, ACOSD, and ATAND were added to
   ! the Fortran standard after the traditional radian functions.
   !---------------------------------------------------------------

   print *, "Trigonometric functions (degrees)"
   print *, "---------------------------------"
   print *, "sind(a)       = ", sind(a)
   print *, "cosd(a)       = ", cosd(a)
   print *, "tand(a)       = ", tand(a)
   print *, "asind(b)      = ", asind(b)
   print *, "acosd(b)      = ", acosd(b)
   print *, "atand(b)      = ", atand(b)
   print *, "atan2d(y,x)   = ", atan2d(y, x)
   print *

   ! Exact-value checks are especially useful for the degree
   ! functions.
   print *, "Degree-function checks"
   print *, "----------------------"
   print *, "sind(30)      = ", sind(30.0_dp)
   print *, "cosd(60)      = ", cosd(60.0_dp)
   print *, "tand(45)      = ", tand(45.0_dp)
   print *, "sind(90)      = ", sind(90.0_dp)
   print *, "cosd(180)     = ", cosd(180.0_dp)
   print *

   !---------------------------------------------------------------
   ! Hyperbolic functions
   !---------------------------------------------------------------

   print *, "Hyperbolic functions"
   print *, "--------------------"
   print *, "sinh(x)       = ", sinh(x)
   print *, "cosh(x)       = ", cosh(x)
   print *, "tanh(x)       = ", tanh(x)
   print *, "asinh(x)      = ", asinh(x)
   print *, "acosh(c)      = ", acosh(c)
   print *, "atanh(b)      = ", atanh(b)
   print *

   !---------------------------------------------------------------
   ! Bessel functions
   !---------------------------------------------------------------

   print *, "Bessel functions"
   print *, "----------------"
   print *, "bessel_j0(x)  = ", bessel_j0(x)
   print *, "bessel_j1(x)  = ", bessel_j1(x)
   print *, "bessel_jn(n,x)= ", bessel_jn(n, x)
   print *, "bessel_y0(x)  = ", bessel_y0(x)
   print *, "bessel_y1(x)  = ", bessel_y1(x)
   print *, "bessel_yn(n,x)= ", bessel_yn(n, x)
   print *

   ! The transformational forms produce a vector of Bessel
   ! functions for consecutive integer orders.
   print *, "Bessel sequences"
   print *, "----------------"
   print *, "J_0 ... J_5   = ", bessel_jn(0, 5, x)
   print *, "Y_0 ... Y_5   = ", bessel_yn(0, 5, x)
   print *

   !---------------------------------------------------------------
   ! Error functions
   !---------------------------------------------------------------

   print *, "Error functions"
   print *, "---------------"
   print *, "erf(x)        = ", erf(x)
   print *, "erfc(x)       = ", erfc(x)
   print *, "erfc_scaled(x)= ", erfc_scaled(x)
   print *

   !---------------------------------------------------------------
   ! Gamma functions
   !---------------------------------------------------------------

   print *, "Gamma functions"
   print *, "---------------"
   print *, "gamma(x)      = ", gamma(x)
   print *, "log_gamma(x)  = ", log_gamma(x)
   print *, "gamma(5)      = ", gamma(5.0_dp)
   print *

   !---------------------------------------------------------------
   ! Hypotenuse
   !---------------------------------------------------------------

   print *, "Hypotenuse"
   print *, "----------"
   print *, "hypot(3,4)    = ", hypot(3.0_dp, 4.0_dp)
   print *

   !---------------------------------------------------------------
   ! Fractional/remainder-related functions
   !---------------------------------------------------------------

   print *, "Remainder and decomposition"
   print *, "---------------------------"
   print *, "mod(5.5,2)   = ", mod(5.5_dp, 2.0_dp)
   print *, "modulo(5.5,2)= ", modulo(5.5_dp, 2.0_dp)
   print *, "fraction(x)   = ", fraction(x)
   print *, "exponent(x)   = ", exponent(x)
   print *, "scale(x,3)    = ", scale(x, 3)
   print *, "set_exponent(x,3) = ", set_exponent(x, 3)
   print *

   !---------------------------------------------------------------
   ! Nearest representable numbers
   !---------------------------------------------------------------

   print *, "Floating-point neighbors"
   print *, "------------------------"
   print *, "nearest(x,+1) = ", nearest(x, 1.0_dp)
   print *, "nearest(x,-1) = ", nearest(x, -1.0_dp)
   print *, "spacing(x)    = ", spacing(x)
   print *, "rrspacing(x)  = ", rrspacing(x)
   print *

   !---------------------------------------------------------------
   ! Model characteristics
   !---------------------------------------------------------------

   print *, "Floating-point model"
   print *, "--------------------"
   print *, "epsilon(x)    = ", epsilon(x)
   print *, "tiny(x)       = ", tiny(x)
   print *, "huge(x)       = ", huge(x)
   print *, "digits(x)     = ", digits(x)
   print *, "precision(x)  = ", precision(x)
   print *, "range(x)      = ", range(x)
   print *, "radix(x)      = ", radix(x)
   print *

   !---------------------------------------------------------------
   ! Numeric inquiry functions
   !---------------------------------------------------------------

   print *, "Selected numeric functions"
   print *, "--------------------------"
   print *, "abs(-x)       = ", abs(-x)
   print *, "dim(y,x)      = ", dim(y, x)
   print *, "max(x,y)      = ", max(x, y)
   print *, "min(x,y)      = ", min(x, y)
   print *, "sign(x,-y)    = ", sign(x, -y)
   print *

   !---------------------------------------------------------------
   ! Rounding
   !---------------------------------------------------------------

   print *, "Rounding"
   print *, "--------"
   print *, "aint(1.7)     = ", aint(1.7_dp)
   print *, "anint(1.7)    = ", anint(1.7_dp)
   print *, "floor(1.7)    = ", floor(1.7_dp)
   print *, "ceiling(1.2)  = ", ceiling(1.2_dp)
   print *, "nint(1.7)     = ", nint(1.7_dp)
   print *

end program test_modern_math_intrinsics
