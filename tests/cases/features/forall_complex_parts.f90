program main
   implicit none
   complex :: z(4), a(2,2)
   type :: box
      complex :: z
      complex, pointer :: p
   end type
   type(box) :: records(4)
   complex, target :: targets(4)
   integer :: i, j

   z = [(1.0,10.0), (2.0,20.0), (3.0,30.0), (4.0,40.0)]
   forall(i=2:4) z(i)%re = z(i-1)%re
   print *, z%re, z%im

   ! Mask is fixed for the entire construct; each statement is simultaneous.
   forall(i=1:4, z(i)%re > 1.0)
      z(i)%re = -z(i)%re
      z(i)%im = z(5-i)%im + z(i)%re
   end forall
   print *, z%re, z%im

   a = reshape([(1.0,10.0),(2.0,20.0),(3.0,30.0),(4.0,40.0)], [2,2])
   forall(i=1:2,j=1:2) a(i,j)%im = a(j,i)%im
   print *, a%re, a%im
   forall(i=1:2) a(:,i)%re = a(:,3-i)%re
   print *, a%re, a%im

   records%z = [(1.0,10.0), (2.0,20.0), (3.0,30.0), (4.0,40.0)]
   forall(i=4:2:-1) records(i)%z%re = records(i-1)%z%re
   forall(i=1:4) records(i)%z%im = records(5-i)%z%im
   print *, records%z%re, records%z%im

   z = [(2.0,10.0), (3.0,20.0), (4.0,30.0), (1.0,40.0)]
   forall(i=1:4) z(int(z(i)%re))%re = real(i)
   print *, z%re, z%im
   forall(i=4:1) z(i)%im = -1.0
   forall(i=1:4,.false.) z(i)%im = -2.0
   print *, z%re, z%im

   targets = z
   do i=1,4
      records(i)%p => targets(i)
   end do
   forall(i=1:4) records(i)%p%re = records(5-i)%p%re
   print *, targets%re, targets%im
end program
