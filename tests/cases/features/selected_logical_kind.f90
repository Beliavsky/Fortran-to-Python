program test_selected_logical_kind
   implicit none
   integer, parameter :: lk = selected_logical_kind(8)
   logical(kind=lk) :: value
   value = .true.
   print *, merge(1,0,value),merge(1,0,lk>0)
end program test_selected_logical_kind
