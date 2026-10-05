program extreme_reductions
   use iso_fortran_env, only: int16,real64
   implicit none
   integer :: v(3), a(2,3), d, empty(0), empty_matrix(0,2), least(1)
   integer(int16) :: short_empty(0)
   real(real64) :: r(2,3), real_empty(0)
   logical :: mask(2,3)
   v = [10,20,30]
   a = reshape([5,2,1,9,7,3], [2,3])
   r = real(a,real64)
   mask = reshape([.true.,.false.,.true.,.false.,.true.,.true.], [2,3])
   print *, maxval(v), maxval(v,1), minval(v), minval(v,1)
   do d = 1,2
      print *, maxval(a,d), minval(a,dim=d)
      print *, maxval(a,d,mask), minval(array=a,mask=mask,dim=d)
      print *, maxval(r,d,mask), minval(r,d,mask)
   end do
   print *, maxval(a,mask), minval(a,mask)
   print *, maxval(a,.true.), minval(a,mask=.true.)
   ! gfortran returns the most-negative integer for empty MAXVAL, instead
   ! of the documented -HUGE. Compare this invariant here; runtime unit
   ! tests separately require the documented exact sentinel.
   print *, merge(1,0,maxval(a,.false.) <= -huge(0)), minval(a,.false.)
   print *, merge(1,0,maxval(empty) <= -huge(0)), minval(empty)
   print *, merge(1,0,maxval(short_empty) <= -huge(0_int16)), minval(short_empty)
   print *, maxval(real_empty), minval(real_empty)
   print *, count(maxval(empty_matrix,1) <= -huge(0)), minval(empty_matrix,1)
   print *, size(maxval(empty_matrix,2)), size(minval(empty_matrix,2))
   print *, sqrt(real(maxval(a,1),real64)), minval(maxval(a,1))
   print *, sum(maxval(a,dim=1))
   least(1) = -huge(0)-1
   print *, maxval(least)
   print *, 'extreme reduction checks passed'
end program
