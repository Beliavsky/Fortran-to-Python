module pair_module
   implicit none
   type :: pair
      integer :: left,right
   end type pair
contains
   function swapped(value) result(other)
      type(pair), intent(in) :: value
      type(pair) :: other
      other%left = value%right
      other%right = value%left
   end function swapped
end module pair_module
program derived_type_arguments
   use pair_module
   implicit none
   type(pair) :: a,b
   a%left = 2
   a%right = 5
   b = swapped(a)
   print *, a%left,a%right,b%left,b%right
end program derived_type_arguments
