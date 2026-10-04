program test_new_math_intrinsics
   use iso_fortran_env, only : real64
   implicit none

   integer, parameter :: dp = real64

   integer :: ntest
   integer :: nfail
   real(dp) :: x

   ntest = 0
   nfail = 0

   print *
   print *, "Testing newer Fortran mathematical intrinsics"
   print *, "=============================================="
   print *

   !---------------------------------------------------------------
   ! Fortran 2008: inverse hyperbolic functions
   !---------------------------------------------------------------

   call check(ntest, nfail, "asinh(0)", asinh(0.0_dp), 0.0_dp)
   call check(ntest, nfail, "acosh(1)", acosh(1.0_dp), 0.0_dp)
   call check(ntest, nfail, "atanh(0)", atanh(0.0_dp), 0.0_dp)

   call check(ntest, nfail, "sinh(asinh(0.5))", &
      sinh(asinh(0.5_dp)), 0.5_dp)

   call check(ntest, nfail, "cosh(acosh(2))", &
      cosh(acosh(2.0_dp)), 2.0_dp)

   call check(ntest, nfail, "tanh(atanh(0.5))", &
      tanh(atanh(0.5_dp)), 0.5_dp)

   !---------------------------------------------------------------
   ! Fortran 2008: error functions
   !---------------------------------------------------------------

   call check(ntest, nfail, "erf(0)", erf(0.0_dp), 0.0_dp)
   call check(ntest, nfail, "erfc(0)", erfc(0.0_dp), 1.0_dp)
   call check(ntest, nfail, "erfc_scaled(0)", erfc_scaled(0.0_dp), 1.0_dp)

   x = 0.7_dp
   call check(ntest, nfail, "erf(x)+erfc(x)", &
      erf(x) + erfc(x), 1.0_dp)

   !---------------------------------------------------------------
   ! Fortran 2008: gamma functions
   !---------------------------------------------------------------

   call check(ntest, nfail, "gamma(1)", gamma(1.0_dp), 1.0_dp)
   call check(ntest, nfail, "gamma(2)", gamma(2.0_dp), 1.0_dp)
   call check(ntest, nfail, "gamma(3)", gamma(3.0_dp), 2.0_dp)
   call check(ntest, nfail, "gamma(4)", gamma(4.0_dp), 6.0_dp)
   call check(ntest, nfail, "gamma(5)", gamma(5.0_dp), 24.0_dp)

   call check(ntest, nfail, "log_gamma(1)", log_gamma(1.0_dp), 0.0_dp)
   call check(ntest, nfail, "exp(log_gamma(5))", &
      exp(log_gamma(5.0_dp)), 24.0_dp)

   !---------------------------------------------------------------
   ! Fortran 2008: hypot
   !---------------------------------------------------------------

   call check(ntest, nfail, "hypot(3,4)", &
      hypot(3.0_dp, 4.0_dp), 5.0_dp)

   call check(ntest, nfail, "hypot(5,12)", &
      hypot(5.0_dp, 12.0_dp), 13.0_dp)

   !---------------------------------------------------------------
   ! Fortran 2008: Bessel functions
   !
   ! Some exact and recurrence identities are used so that the
   ! test does not need a table of decimal constants.
   !---------------------------------------------------------------

   call check(ntest, nfail, "bessel_j0(0)", &
      bessel_j0(0.0_dp), 1.0_dp)

   call check(ntest, nfail, "bessel_j1(0)", &
      bessel_j1(0.0_dp), 0.0_dp)

   x = 2.5_dp

   call check(ntest, nfail, "bessel_jn(0,x)", &
      bessel_jn(0, x), bessel_j0(x))

   call check(ntest, nfail, "bessel_jn(1,x)", &
      bessel_jn(1, x), bessel_j1(x))

   call check(ntest, nfail, "bessel_yn(0,x)", &
      bessel_yn(0, x), bessel_y0(x))

   call check(ntest, nfail, "bessel_yn(1,x)", &
      bessel_yn(1, x), bessel_y1(x))

   ! J_{n+1}(x) = 2*n/x J_n(x) - J_{n-1}(x)

   call check(ntest, nfail, "Bessel J recurrence", &
      bessel_jn(3, x), &
      4.0_dp/x*bessel_jn(2, x) - bessel_jn(1, x), &
      100.0_dp)

   ! Same recurrence for Y_n.

   call check(ntest, nfail, "Bessel Y recurrence", &
      bessel_yn(3, x), &
      4.0_dp/x*bessel_yn(2, x) - bessel_yn(1, x), &
      100.0_dp)

   !---------------------------------------------------------------
   ! Fortran 2008: NORM2
   !---------------------------------------------------------------

   block
      real(dp) :: v(2)

      v = [3.0_dp, 4.0_dp]
      call check(ntest, nfail, "norm2([3,4])", norm2(v), 5.0_dp)
   end block

   !---------------------------------------------------------------
   ! Fortran 2023: trigonometric functions in degrees
   !---------------------------------------------------------------

   print *
   print *, "Fortran 2023 degree trigonometric functions"
   print *

   call check(ntest, nfail, "sind(0)", sind(0.0_dp), 0.0_dp)
   call check(ntest, nfail, "sind(30)", sind(30.0_dp), 0.5_dp)
   call check(ntest, nfail, "sind(90)", sind(90.0_dp), 1.0_dp)
   call check(ntest, nfail, "sind(180)", sind(180.0_dp), 0.0_dp)

   call check(ntest, nfail, "cosd(0)", cosd(0.0_dp), 1.0_dp)
   call check(ntest, nfail, "cosd(60)", cosd(60.0_dp), 0.5_dp)
   call check(ntest, nfail, "cosd(90)", cosd(90.0_dp), 0.0_dp)
   call check(ntest, nfail, "cosd(180)", cosd(180.0_dp), -1.0_dp)

   call check(ntest, nfail, "tand(0)", tand(0.0_dp), 0.0_dp)
   call check(ntest, nfail, "tand(45)", tand(45.0_dp), 1.0_dp)

   call check(ntest, nfail, "asind(0)", asind(0.0_dp), 0.0_dp)
   call check(ntest, nfail, "asind(0.5)", asind(0.5_dp), 30.0_dp)
   call check(ntest, nfail, "asind(1)", asind(1.0_dp), 90.0_dp)

   call check(ntest, nfail, "acosd(1)", acosd(1.0_dp), 0.0_dp)
   call check(ntest, nfail, "acosd(0.5)", acosd(0.5_dp), 60.0_dp)
   call check(ntest, nfail, "acosd(0)", acosd(0.0_dp), 90.0_dp)
   call check(ntest, nfail, "acosd(-1)", acosd(-1.0_dp), 180.0_dp)

   call check(ntest, nfail, "atand(0)", atand(0.0_dp), 0.0_dp)
   call check(ntest, nfail, "atand(1)", atand(1.0_dp), 45.0_dp)

   call check(ntest, nfail, "atan2d(1,1)", &
      atan2d(1.0_dp, 1.0_dp), 45.0_dp)

   call check(ntest, nfail, "atan2d(1,0)", &
      atan2d(1.0_dp, 0.0_dp), 90.0_dp)

   call check(ntest, nfail, "atan2d(0,-1)", &
      atan2d(0.0_dp, -1.0_dp), 180.0_dp)

   ! ATAND has a two-argument Fortran 2023 form as well.

   call check(ntest, nfail, "atand(1,1)", &
      atand(1.0_dp, 1.0_dp), 45.0_dp)

   !---------------------------------------------------------------
   ! Fortran 2023: PI-scaled trigonometric functions
   !
   ! sinpi(x) = sin(pi*x), etc., but without requiring the caller
   ! to form pi*x.
   !---------------------------------------------------------------

   print *
   print *, "Fortran 2023 PI-scaled functions"
   print *

   call check(ntest, nfail, "sinpi(0)", sinpi(0.0_dp), 0.0_dp)
   call check(ntest, nfail, "sinpi(0.5)", sinpi(0.5_dp), 1.0_dp)
   call check(ntest, nfail, "sinpi(1)", sinpi(1.0_dp), 0.0_dp)
   call check(ntest, nfail, "sinpi(1.5)", sinpi(1.5_dp), -1.0_dp)

   call check(ntest, nfail, "cospi(0)", cospi(0.0_dp), 1.0_dp)
   call check(ntest, nfail, "cospi(0.5)", cospi(0.5_dp), 0.0_dp)
   call check(ntest, nfail, "cospi(1)", cospi(1.0_dp), -1.0_dp)
   call check(ntest, nfail, "cospi(2)", cospi(2.0_dp), 1.0_dp)

   call check(ntest, nfail, "tanpi(0)", tanpi(0.0_dp), 0.0_dp)
   call check(ntest, nfail, "tanpi(0.25)", tanpi(0.25_dp), 1.0_dp)

   call check(ntest, nfail, "asinpi(0)", asinpi(0.0_dp), 0.0_dp)
   call check(ntest, nfail, "asinpi(0.5)", asinpi(0.5_dp), 1.0_dp/6.0_dp)
   call check(ntest, nfail, "asinpi(1)", asinpi(1.0_dp), 0.5_dp)

   call check(ntest, nfail, "acospi(1)", acospi(1.0_dp), 0.0_dp)
   call check(ntest, nfail, "acospi(0)", acospi(0.0_dp), 0.5_dp)
   call check(ntest, nfail, "acospi(-1)", acospi(-1.0_dp), 1.0_dp)

   call check(ntest, nfail, "atanpi(0)", atanpi(0.0_dp), 0.0_dp)
   call check(ntest, nfail, "atanpi(1)", atanpi(1.0_dp), 0.25_dp)

   call check(ntest, nfail, "atan2pi(1,1)", &
      atan2pi(1.0_dp, 1.0_dp), 0.25_dp)

   call check(ntest, nfail, "atan2pi(1,0)", &
      atan2pi(1.0_dp, 0.0_dp), 0.5_dp)

   !---------------------------------------------------------------
   ! Elemental behavior
   !---------------------------------------------------------------

   block
      real(dp) :: a(4)
      real(dp) :: s(4)
      real(dp) :: expected(4)

      a = [0.0_dp, 30.0_dp, 90.0_dp, 180.0_dp]
      expected = [0.0_dp, 0.5_dp, 1.0_dp, 0.0_dp]

      s = sind(a)

      call check_vector(ntest, nfail, "elemental SIND", s, expected)
   end block

   block
      real(dp) :: a(5)
      real(dp) :: s(5)
      real(dp) :: expected(5)

      a = [0.0_dp, 0.5_dp, 1.0_dp, 1.5_dp, 2.0_dp]
      expected = [0.0_dp, 1.0_dp, 0.0_dp, -1.0_dp, 0.0_dp]

      s = sinpi(a)

      call check_vector(ntest, nfail, "elemental SINPI", s, expected)
   end block

   !---------------------------------------------------------------
   ! Summary
   !---------------------------------------------------------------

   print *
   print *, "=============================================="
   print *, "Tests run: ", ntest
   print *, "Failures : ", nfail

   if (nfail == 0) then
      print *, "ALL TESTS PASSED"
   else
      print *, "SOME TESTS FAILED"
      error stop 1
   end if

contains

   subroutine check(ntest, nfail, name, got, expected, tolerance_factor)
      integer, intent(inout) :: ntest, nfail
      character(len=*), intent(in) :: name
      real(dp), intent(in) :: got
      real(dp), intent(in) :: expected
      real(dp), intent(in), optional :: tolerance_factor

      real(dp) :: tol
      real(dp) :: factor
      real(dp) :: scale_value

      ntest = ntest + 1

      factor = 20.0_dp
      if (present(tolerance_factor)) factor = tolerance_factor

      scale_value = max(1.0_dp, abs(expected))
      tol = factor*epsilon(1.0_dp)*scale_value

      if (abs(got - expected) <= tol) then
         print "(a,1x,a)", "PASS", trim(name)
      else
         nfail = nfail + 1
         print "(a,1x,a)", "FAIL", trim(name)
         print "(a,es24.16)", "   got      = ", got
         print "(a,es24.16)", "   expected = ", expected
         print "(a,es24.16)", "   error    = ", abs(got - expected)
         print "(a,es24.16)", "   tolerance= ", tol
      end if
   end subroutine check


   subroutine check_vector(ntest, nfail, name, got, expected)
      integer, intent(inout) :: ntest, nfail
      character(len=*), intent(in) :: name
      real(dp), intent(in) :: got(:)
      real(dp), intent(in) :: expected(:)

      integer :: i
      logical :: ok
      real(dp) :: tol

      ntest = ntest + 1
      tol = 20.0_dp*epsilon(1.0_dp)

      ok = size(got) == size(expected)

      if (ok) then
         do i = 1, size(got)
            if (abs(got(i) - expected(i)) > tol) then
               ok = .false.
               exit
            end if
         end do
      end if

      if (ok) then
         print "(a,1x,a)", "PASS", trim(name)
      else
         nfail = nfail + 1
         print "(a,1x,a)", "FAIL", trim(name)
         print *, "   got      = ", got
         print *, "   expected = ", expected
      end if
   end subroutine check_vector

end program test_new_math_intrinsics
