program main
   use iso_fortran_env, only: int8, int16, int64
   implicit none
   integer :: a(4), shifts(4), empty(0)
   integer(int8) :: narrow
   integer(int16) :: medium
   type :: box
      integer(int64) :: value
   end type
   type(box) :: record
   a = [1,2,3,4]
   shifts = [0,1,-1,2]
   print *, ishftc(a,shifts,[1,2,3,4])
   print *, ishftc(a,shifts)
   print *, ishftc(1,[0,1,2,3],4)
   print *, ishftc(11,1,3), ishftc(11,-1,3)
   print *, ishftc(-1,1,3), ishftc(1,32), ishftc(1,-32)
   narrow = 1
   medium = 1
   print *, ishftc(narrow,-1), kind(ishftc(narrow,1))
   print *, ishftc(medium,-1), kind(ishftc(medium,1))
   record%value = 1
   print *, ishftc(size=64,shift=-1,i=record%value)
   print *, kind(ishftc(not(record%value),1)), not(ishftc(1_int64,1))
   print *, size(ishftc(empty,1))
end program
