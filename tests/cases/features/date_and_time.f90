program main
   implicit none
   character(len=8) :: date
   character(len=10) :: clock
   character(len=5) :: zone
   integer :: values(8), work(16), matrix(8,2)
   integer(kind=8) :: wide(8)
   type :: stamp_box
      character(len=8) :: date
      integer :: values(8)
   end type
   type(stamp_box) :: record
   integer, target :: storage(8)
   integer, pointer :: p(:)

   call date_and_time(date, clock, zone, values)
   print *, date(1:4) /= '    ', clock(7:7) == '.', len_trim(zone) == 5
   print *, values(1) >= 2000, values(2) >= 1, values(2) <= 12
   print *, values(3) >= 1, values(3) <= 31, abs(values(4)) <= 1440
   print *, values(5) >= 0, values(5) < 24, values(6) >= 0, values(6) < 60
   print *, values(7) >= 0, values(7) <= 60, values(8) >= 0, values(8) < 1000
   call date_and_time(values=wide)
   print *, wide(1) >= 2000
   work = -1
   call date_and_time(values=work(1:16:2))
   print *, all(work(2:16:2) == -1), work(1) >= 2000
   matrix = -1
   call date_and_time(values=matrix(:,2))
   print *, all(matrix(:,1) == -1), matrix(1,2) >= 2000
   call date_and_time(values=record%values,date=record%date)
   print *, record%values(1) >= 2000, len_trim(record%date) == 8
   p => storage
   call date_and_time(values=p)
   print *, storage(1) >= 2000, associated(p,storage)
   date = ' '
   call host_stamp()
   print *, len_trim(date) == 8
   call date_and_time()
contains
   subroutine host_stamp()
      call date_and_time(date=date)
   end subroutine
end program
