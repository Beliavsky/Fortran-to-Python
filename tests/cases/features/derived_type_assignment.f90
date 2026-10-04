module record_module
   implicit none
   type :: record
      integer :: id
      real(kind=kind(1d0)) :: values(2)
   end type record
end module record_module
program derived_type_assignment
   use record_module
   implicit none
   type(record) :: a,b
   a%id = 7
   a%values = [1d0,2d0]
   b = a
   b%values(1) = 9d0
   print *, a%id,b%id,a%values(1),b%values(1)
end program derived_type_assignment
