program main
   implicit none
   type :: inner_box
      real :: samples(2)
   end type
   type :: box
      integer :: integers(3), matrix(2,2)
      real :: samples(2)
      complex :: z(2)
      logical :: flags(2)
      character(len=3) :: labels(2)
      type(inner_box) :: inner
      integer, allocatable :: allocated_values(:)
      integer, pointer :: alias(:)
   end type
   type(box), target :: record
   type(box) :: records(2)
   real, pointer :: view(:)
   integer, target :: target_values(3)

   view => record%samples
   record%integers = 3.9
   record%samples = -1
   record%matrix = 7
   record%z = (1.0,2.0)
   record%flags = .true.
   record%labels = 'abcdef'
   record%inner%samples = 4
   records(2)%samples = 5
   print *, record%integers, view, record%matrix
   print *, record%z%re, record%z%im, record%flags
   print *, record%labels(1), record%labels(2)
   print *, record%inner%samples, records(2)%samples
   where (record%samples < 0)
      record%samples = 8
   elsewhere
      record%samples = 9
   end where
   print *, view

   allocate(record%allocated_values(3))
   record%allocated_values = -2
   print *, record%allocated_values, lbound(record%allocated_values), ubound(record%allocated_values)
   record%alias => target_values
   record%alias = 11
   print *, target_values, associated(record%alias,target_values)
end program
