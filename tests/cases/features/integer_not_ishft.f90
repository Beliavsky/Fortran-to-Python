program main
   use iso_fortran_env, only: int8, int16, int32, int64
   implicit none
   integer :: a(4), shifts(4), empty(0)
   integer(int8) :: narrow
   integer(int16) :: medium
   integer(int64) :: wide
   logical :: flags(4)
   type :: box
      integer(int64) :: value
   end type
   type(box) :: record
   a = [1,2,3,4]
   shifts = [0,1,-1,2]
   flags = [.true.,.false.,.true.,.false.]
   print *, not(a)
   print *, ishft(a,shifts)
   print *, ishft(1,[0,1,2,3])
   print *, ishft(-1,-1), ishft(-1,1), ishft(1,31)
   print *, ishft(-1,32), ishft(-1,-32)
   print *, .not. flags, .not. (.true.)
   print *, .not. (.not. flags), all(.not. (.not. flags))
   narrow = 1
   medium = 1
   wide = -1
   print *, not(narrow), ishft(narrow,7), kind(not(narrow)), kind(ishft(narrow,0))
   print *, not(medium), ishft(medium,15), kind(not(medium))
   print *, ishft(wide,-1), ishft(1_int64,63)
   record%value = 1
   print *, ishft(i=record%value,shift=63), kind(not(record%value))
   print *, kind(ishft(not(1_int64), -1)), not(ishft(1_int64,1))
   print *, size(not(empty)), size(ishft(empty,1))
   print *, 'not(1) ishft(1,2)'
end program
