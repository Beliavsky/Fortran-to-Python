module extension_bindings
   implicit none
   type :: base
      integer :: id = 1
   contains
      procedure :: increment
      procedure :: step
      procedure :: read_value
   end type
   type, extends(base) :: child
      integer :: extra = 8
   contains
      procedure :: step => child_step
   end type
contains
   subroutine increment(self,n)
      class(base), intent(inout) :: self
      integer, intent(in) :: n
      call self%step(n)
   end subroutine
   subroutine step(self,n)
      class(base), intent(inout) :: self
      integer, intent(in) :: n
      self%id = self%id + n
   end subroutine
   subroutine child_step(self,n)
      class(child), intent(inout) :: self
      integer, intent(in) :: n
      self%id = self%id + 2*n
   end subroutine
   integer function read_value(self) result(value)
      class(base), intent(in) :: self
      value = self%id
   end function
end module
program type_extension_bindings
   use extension_bindings
   implicit none
   type(child) :: value
   call value%increment(3)
   print *, value%read_value(),value%base%read_value()
   call value%base%increment(4)
   print *, value%id,value%base%id,value%extra
end program
