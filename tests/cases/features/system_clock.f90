program main
   implicit none
   integer :: count, rate, maximum, values(3), matrix(2,2), from_dummy
   integer(kind=8) :: wide_count, wide_rate, wide_max
   real :: real_rate
   type :: clock_box
      integer :: count, samples(2)
      integer, pointer :: alias => null()
   end type
   type(clock_box) :: record, records(2)
   integer, target :: storage
   integer, pointer :: p

   count = -1
   rate = -1
   maximum = -1
   call system_clock(count, rate, maximum)
   print *, rate > 0, maximum > 0, count >= 0, count <= maximum
   call system_clock(count_max=maximum, count_rate=real_rate, count=count)
   print *, real_rate > 0.0, count >= 0, count <= maximum
   call system_clock(count_rate=rate)
   call system_clock(count_max=maximum)
   print *, rate > 0, maximum > 0
   call system_clock(wide_count, wide_rate, wide_max)
   print *, wide_rate > 0, wide_count >= 0, wide_count <= wide_max

   values = -1
   matrix = -1
   record%count = -1
   record%samples = -1
   records(2)%count = -1
   call system_clock(values(1), values(2), values(3))
   call system_clock(matrix(1,2))
   call system_clock(record%count, record%samples(1), records(2)%count)
   print *, values(1) >= 0, values(2) > 0, values(3) > 0, matrix(1,2) >= 0
   print *, record%count >= 0, record%samples(1) > 0, records(2)%count > 0
   from_dummy = -1
   call stamp(from_dummy)
   print *, from_dummy >= 0
   rate = -1
   call host_stamp()
   print *, rate > 0
   p => storage
   storage = -1
   call system_clock(p)
   print *, storage >= 0, p == storage
   record%alias => storage
   storage = -1
   call system_clock(count=record%alias)
   print *, storage >= 0, record%alias == storage, associated(record%alias,storage)
   call system_clock()
contains
   subroutine stamp(value)
      integer :: value
      call system_clock(value)
   end subroutine
   subroutine host_stamp()
      call system_clock(count_rate=rate)
   end subroutine
end program
