module bound_module
   implicit none
   type :: counter
      integer :: value = 0
   contains
      procedure :: increment
   end type counter
contains
   subroutine increment(self,n)
      class(counter), intent(inout) :: self
      integer, intent(in) :: n
      self%value = self%value + n
   end subroutine increment
end module bound_module
program type_bound_procedure
   use bound_module
   implicit none
   type(counter) :: value
   call value%increment(3)
   print *, value%value
end program type_bound_procedure
