module data_storage
   implicit none
   integer :: seed
   data seed /7/
contains
   subroutine bump()
      integer :: count, a(2)
      data count /0/ a /1, 2/
      count = count + 1
      a = a + count
      print *, count, a
   end subroutine bump

   integer function next_count() result(value)
      integer :: count
      data count /10/
      count = count + 1
      value = count
   end function next_count
end module data_storage

program data_initializers
   use data_storage
   implicit none
   integer, parameter :: n = 3
   integer :: i, j, k, v(n), a(-1:0,2:4)
   real :: x, y
   logical :: flags(3)
   complex :: z
   character(len=8) :: name
   character(len=4) :: words(3)
   data i, j, k /3*5/
   data x /2.5/ y /7.25/
   data name /'fortran'/
   data v /10, 20, 30/
   data a /1, 2, 3, 4, 5, 6/
   data flags /2*.true., .false./
   data z /(1.0, -2.0)/
   data words /'a/b', 'x,y', '123456'/
   print *, i, j, k, x, y
   print *, '[' // name // ']'
   print *, v
   print *, a
   print *, a(-1,:), a(0,:)
   print *, count(flags), real(z), aimag(z)
   print *, '[' // words(1) // ']', '[' // words(2) // ']', '[' // words(3) // ']'
   print *, seed
   call bump()
   call bump()
   call bump()
   print *, next_count()
   print *, next_count()
end program data_initializers
