module bound_module
   implicit none
   type :: counter
      integer :: value = 0
      integer :: samples(2)
   contains
      procedure :: increment => add_value
      procedure, pass(object) :: shift => shift_value
      procedure :: reset
      procedure :: read_value
      procedure :: export_value
      procedure, nopass :: twice
   end type counter
   type :: box
      type(counter) :: item
   end type box
contains
   subroutine add_value(self,n)
      class(counter), intent(inout) :: self
      integer, intent(in) :: n
      call self%shift(n)
   end subroutine add_value
   subroutine shift_value(n,object)
      integer, intent(in) :: n
      class(counter), intent(inout) :: object
      object%value = object%value + n
   end subroutine shift_value
   subroutine reset(self)
      class(counter), intent(inout) :: self
      self%value = 0
   end subroutine reset
   integer function read_value(self,extra) result(value)
      class(counter), intent(in) :: self
      integer, intent(in), optional :: extra
      value = self%value
      if (present(extra)) value = value + extra
   end function read_value
   subroutine export_value(self,value)
      class(counter), intent(inout) :: self
      integer, intent(out) :: value
      self%value = self%value + 1
      value = self%value
   end subroutine export_value
   integer function twice(n) result(value)
      integer, intent(in) :: n
      value = 2*n
   end function twice
end module bound_module
program type_bound_procedure
   use bound_module
   implicit none
   type(counter) :: value
   type(box) :: nested
   integer :: exported
   value%samples = [2,4]
   call value%increment(3)
   print *, value%value
   call value%increment(n=2)
   call value%shift(4)
   print *, value%read_value(), value%read_value(extra=7)
   print *, value%twice(6), value%samples(2)
   call value%export_value(exported)
   print *, exported, value%value
   call value%reset
   print *, value%value
   call nested%item%increment(8)
   print *, nested%item%read_value()
end program type_bound_procedure
