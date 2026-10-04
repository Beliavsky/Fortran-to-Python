program optional_arguments
   implicit none
   print *, add(3), add(3,4), add(offset=5,value=2)
contains
   integer function add(value,offset) result(total)
      integer, intent(in) :: value
      integer, intent(in), optional :: offset
      total = value
      if (present(offset)) total = total + offset
   end function add
end program optional_arguments
