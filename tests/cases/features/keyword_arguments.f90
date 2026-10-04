program keyword_arguments
   implicit none
   print *, combine(2,3), combine(b=2,a=3)
contains
   integer function combine(a,b)
      integer, intent(in) :: a,b
      combine = 10*a + b
   end function combine
end program keyword_arguments
