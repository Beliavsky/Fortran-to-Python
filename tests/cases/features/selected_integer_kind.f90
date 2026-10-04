program selected_integer_kind
   implicit none
   integer, parameter :: ik = selected_int_kind(12)
   integer(kind=ik) :: value
   value = 123456789012_ik
   print *, value, value+1_ik, merge(1,0,ik>0)
end program selected_integer_kind
