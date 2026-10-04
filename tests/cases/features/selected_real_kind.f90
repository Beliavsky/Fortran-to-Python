program test_selected_real_kind
   implicit none
   integer, parameter :: rk = selected_real_kind(p=12,r=100)
   real(kind=rk) :: value
   value = 1.25_rk
   print *, value,value*2.0_rk,merge(1,0,rk>0)
end program test_selected_real_kind
