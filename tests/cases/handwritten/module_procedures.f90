module arithmetic_mod
   implicit none
contains
   function twice(n) result(value)
      integer, intent(in) :: n
      integer :: value
      value = n * 2
   end function twice
end module arithmetic_mod
program module_procedures
   use arithmetic_mod, only: twice
   implicit none
   print *, twice(7)
end program module_procedures
