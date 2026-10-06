program main
   implicit none
   type :: inner_box
      complex :: z
   end type
   type :: box
      type(inner_box) :: inner
      complex :: z
      complex, pointer :: p
   end type
   type(box) :: records(2), matrix(2,2)
   complex, target :: targets(2)
   integer :: calls

   calls = 0
   records%z = (1.0,2.0)
   records%z%re = next_values()
   records%z%im = records%z%re + 10.0
   print *, calls, records%z%re, records%z%im
   where (records%z%re > 3.0)
      records%z%im = -1.0
   elsewhere
      records%z%re = 9.0
   end where
   print *, records%z%re, records%z%im

   records%inner%z = (5.0,6.0)
   records%inner%z%re = [7.0,8.0]
   records%inner%z%im = records%inner%z%re
   print *, records%inner%z%re, records%inner%z%im

   matrix%z = (1.0,2.0)
   matrix%z%re = reshape([3.0,4.0,5.0,6.0], [2,2])
   where (matrix%z%re > 4.0) matrix%z%im = 10.0
   print *, matrix%z%re, matrix%z%im

   targets = [(1.0,2.0), (3.0,4.0)]
   records(1)%p => targets(1)
   records(2)%p => targets(2)
   records(1)%p%re = 11.0
   records(2)%p%re = 12.0
   records(1)%p%im = 13.0
   records(2)%p%im = 13.0
   print *, targets%re, targets%im
contains
   function next_values() result(values)
      real :: values(2)
      calls = calls + 1
      values = [3.0,4.0]
   end function
end program
