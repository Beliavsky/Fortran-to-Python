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

   call check("asinh(0)", asinh(0.0_dp), 0.0_dp)
   call check("acosh(1)", acosh(1.0_dp), 0.0_dp)
   call check("atanh(0)", atanh(0.0_dp), 0.0_dp)

   call check("sinh(asinh(0.5))", &
      sinh(asinh(0.5_dp)), 0.5_dp)

   call check("cosh(acosh(2))", &
      cosh(acosh(2.0_dp)), 2.0_dp)

   call check("tanh(atanh(0.5))", &
      tanh(atanh(0.5_dp)), 0.5_dp)

   !---------------------------------------------------------------
   ! Fortran 2008: error functions
   !---------------------------------------------------------------

   call check("erf(0)", erf(0.0_dp), 0.0_dp)
   call check("erfc(0)", erfc(0.0_dp), 1.0_dp)
   call check("erfc_scaled(0)", erfc_scaled(0.0_dp), 1.0_dp)

   x = 0.7_dp
   call check("erf(x)+erfc(x)", &
      erf(x) + erfc(x), 1.0_dp)

   !---------------------------------------------------------------
   ! Fortran 2008: gamma functions
   !---------------------------------------------------------------

   call check("gamma(1)", gamma(1.0_dp), 1.0_dp)
   call check("gamma(2)", gamma(2.0_dp), 1.0_dp)
   call check("gamma(3)", gamma(3.0_dp), 2.0_dp)
   call check("gamma(4)", gamma(4.0_dp), 6.0_dp)
   call check("gamma(5)", gamma(5.0_dp), 24.0_dp)

   call check("log_gamma(1)", log_gamma(1.0_dp), 0.0_dp)
   call check("exp(log_gamma(5))", &
      exp(log_gamma(5.0_dp)), 24.0_dp)

   !---------------------------------------------------------------
   ! Fortran 2008: hypot
   !---------------------------------------------------------------

   call check("hypot(3,4)", &
      hypot(3.0_dp, 4.0_dp), 5.0_dp)

   call check("hypot(5,12)", &
      hypot(5.0_dp, 12.0_dp), 13.0_dp)

   !---------------------------------------------------------------
   ! Fortran 2008: Bessel functions
   !
   ! Some exact and recurrence identities are used so that the
   ! test does not need a table of decimal constants.
   !---------------------------------------------------------------

   call check("bessel_j0(0)", &
      bessel_j0(0.0_dp), 1.0_dp)

   call check("bessel_j1(0)", &
      bessel_j1(0.0_dp), 0.0_dp)

   x = 2.5_dp

   call check("bessel_jn(0,x)", &
      bessel_jn(0, x), bessel_j0(x))

   call check("bessel_jn(1,x)", &
      bessel_jn(1, x), bessel_j1(x))

   call check("bessel_yn(0,x)", &
      bessel_yn(0, x), bessel_y0(x))

   call check("bessel_yn(1,x)", &
      bessel_yn(1, x), bessel_y1(x))

   ! J_{n+1}(x) = 2*n/x J_n(x) - J_{n-1}(x)

   call check("Bessel J recurrence", &
      bessel_jn(3, x), &
      4.0_dp/x*bessel_jn(2, x) - bessel_jn(1, x), &
      100.0_dp)

   ! Same recurrence for Y_n.

   call check("Bessel Y recurrence", &
      bessel_yn(3, x), &
      4.0_dp/x*bessel_yn(2, x) - bessel_yn(1, x), &
      100.0_dp)

   !---------------------------------------------------------------
   ! Fortran 2008: NORM2
   !---------------------------------------------------------------

   block
      real(dp) :: v(2)

      v = [3.0_dp, 4.0_dp]
      call check("norm2([3,4])", norm2(v), 5.0_dp)
   end block

   !---------------------------------------------------------------
   ! Fortran 2023: trigonometric functions in degrees
   !---------------------------------------------------------------

   print *
   print *, "Fortran 2023 degree trigonometric functions"
   print *

   call check("sind(0)", sind(0.0_dp), 0.0_dp)
   call check("sind(30)", sind(30.0_dp), 0.5_dp)
   call check("sind(90)", sind(90.0_dp), 1.0_dp)
   call check("sind(180)", sind(180.0_dp), 0.0_dp)

   call check("cosd(0)", cosd(0.0_dp), 1.0_dp)
   call check("cosd(60)", cosd(60.0_dp), 0.5_dp)
   call check("cosd(90)", cosd(90.0_dp), 0.0_dp)
   call check("cosd(180)", cosd(180.0_dp), -1.0_dp)

   call check("tand(0)", tand(0.0_dp), 0.0_dp)
   call check("tand(45)", tand(45.0_dp), 1.0_dp)

   call check("asind(0)", asind(0.0_dp), 0.0_dp)
   call check("asind(0.5)", asind(0.5_dp), 30.0_dp)
   call check("asind(1)", asind(1.0_dp), 90.0_dp)

   call check("acosd(1)", acosd(1.0_dp), 0.0_dp)
   call check("acosd(0.5)", acosd(0.5_dp), 60.0_dp)
   call check("acosd(0)", acosd(0.0_dp), 90.0_dp)
   call check("acosd(-1)", acosd(-1.0_dp), 180.0_dp)

   call check("atand(0)", atand(0.0_dp), 0.0_dp)
   call check("atand(1)", atand(1.0_dp), 45.0_dp)

   call check("atan2d(1,1)", &
      atan2d(1.0_dp, 1.0_dp), 45.0_dp)

   call check("atan2d(1,0)", &
      atan2d(1.0_dp, 0.0_dp), 90.0_dp)

   call check("atan2d(0,-1)", &
      atan2d(0.0_dp, -1.0_dp), 180.0_dp)

   ! ATAND has a two-argument Fortran 2023 form as well.

   call check("atand(1,1)", &
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

   call check("sinpi(0)", sinpi(0.0_dp), 0.0_dp)
   call check("sinpi(0.5)", sinpi(0.5_dp), 1.0_dp)
   call check("sinpi(1)", sinpi(1.0_dp), 0.0_dp)
   call check("sinpi(1.5)", sinpi(1.5_dp), -1.0_dp)

   call check("cospi(0)", cospi(0.0_dp), 1.0_dp)
   call check("cospi(0.5)", cospi(0.5_dp), 0.0_dp)
   call check("cospi(1)", cospi(1.0_dp), -1.0_dp)
   call check("cospi(2)", cospi(2.0_dp), 1.0_dp)

   call check("tanpi(0)", tanpi(0.0_dp), 0.0_dp)
   call check("tanpi(0.25)", tanpi(0.25_dp), 1.0_dp)

   call check("asinpi(0)", asinpi(0.0_dp), 0.0_dp)
   call check("asinpi(0.5)", asinpi(0.5_dp), 1.0_dp/6.0_dp)
   call check("asinpi(1)", asinpi(1.0_dp), 0.5_dp)

   call check("acospi(1)", acospi(1.0_dp), 0.0_dp)
   call check("acospi(0)", acospi(0.0_dp), 0.5_dp)
   call check("acospi(-1)", acospi(-1.0_dp), 1.0_dp)

   call check("atanpi(0)", atanpi(0.0_dp), 0.0_dp)
   call check("atanpi(1)", atanpi(1.0_dp), 0.25_dp)

   call check("atan2pi(1,1)", &
      atan2pi(1.0_dp, 1.0_dp), 0.25_dp)

   call check("atan2pi(1,0)", &
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

      call check_vector("elemental SIND", s, expected)
   end block

   block
      real(dp) :: a(5)
      real(dp) :: s(5)
      real(dp) :: expected(5)

      a = [0.0_dp, 0.5_dp, 1.0_dp, 1.5_dp, 2.0_dp]
      expected = [0.0_dp, 1.0_dp, 0.0_dp, -1.0_dp, 0.0_dp]

      s = sinpi(a)

      call check_vector("elemental SINPI", s, expected)
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

   subroutine check(name, got, expected, tolerance_factor)
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


   subroutine check_vector(name, got, expected)
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
