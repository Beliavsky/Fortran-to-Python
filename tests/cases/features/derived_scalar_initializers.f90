module initialized_records
   implicit none
   type :: record
      integer :: x = -1, y = -2
   end type record
   type(record), parameter :: seed = record(10, 20)
   type(record) :: first = seed, second = seed
contains
   subroutine step()
      type(record) :: state = record(y=40, x=30)
      print *, state%x, state%y
      state%x = state%x + 1
      state%y = state%y + 2
   end subroutine step

   integer function next_value() result(value)
      type(record) :: state = record(50, 60)
      value = state%x
      state%x = state%x + 1
   end function next_value
end module initialized_records

program derived_scalar_initializers
   use initialized_records
   implicit none
   type :: cc
      real :: x, y
   end type cc
   type(cc) :: z = cc(10.0, 20.0)
   print *, z
   z%x = 3.0
   z%y = 4.0
   print *, z
   print *, z%x, z%y
   first%x = 99
   print *, first%x, second%x, seed%x
   call step()
   call step()
   print *, next_value()
   print *, next_value()
end program derived_scalar_initializers
