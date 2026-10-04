module impure_module
   implicit none
   integer :: calls = 0
contains
   impure elemental integer function counted(value)
      integer, intent(in) :: value
      calls = calls + 1
      counted = value * 2
   end function counted
end module impure_module
program impure_elemental
   use impure_module
   implicit none
   integer :: a,b
   a = counted(3)
   b = counted(5)
   print *, a,b,calls
end program impure_elemental
