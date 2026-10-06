program main
   use iso_fortran_env, only: int8, int16, int64
   implicit none
   integer :: a(4), empty(0)
   integer(int8) :: narrow
   integer(int16) :: medium
   type :: box
      integer(int64) :: value
   end type
   type(box) :: record
   a = [1,2,3,4]
   print *, popcnt(a), poppar(a)
   print *, leadz(a), trailz(a)
   print *, popcnt(0), poppar(0), leadz(0), trailz(0)
   print *, popcnt(-1), poppar(-1), leadz(-1), trailz(-1)
   narrow = -1
   medium = 0
   record%value = -1
   print *, popcnt(narrow), poppar(narrow), leadz(narrow), trailz(narrow)
   print *, leadz(medium), trailz(medium)
   print *, popcnt(i=record%value), poppar(i=record%value)
   print *, kind(popcnt(narrow)), kind(poppar(record%value))
   print *, kind(leadz(medium)), kind(trailz(record%value))
   print *, bit_size(popcnt(record%value)), not(popcnt(record%value))
   print *, popcnt(not(1_int64)), leadz(ishft(1_int64,63)), trailz(ishft(1_int64,63))
   print *, size(popcnt(empty)), size(poppar(empty)), size(leadz(empty)), size(trailz(empty))
   print *, 'popcnt(1) poppar(1) leadz(1) trailz(1)'
end program
