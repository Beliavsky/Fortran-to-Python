program selected_kinds
   implicit none
   integer, parameter :: narrow = selected_int_kind(r=2)
   integer, parameter :: wide = selected_int_kind(12)
   integer, parameter :: rk = selected_real_kind(r=100,p=12)
   integer, parameter :: lk = selected_logical_kind(16)
   integer(kind=narrow) :: small
   integer(kind=wide) :: big(2)
   real(kind=rk) :: x
   logical(kind=lk) :: flag
   small = 100
   big = [123456789012_wide, 123456789013_wide]
   x = 1.25_rk
   flag = .true.
   print *, selected_int_kind(2), selected_int_kind(4), &
      selected_int_kind(9), selected_int_kind(18)
   print *, huge(small), huge(big), digits(big), range(big)
   print *, big
   print *, rk, x, x*2.0_rk
   print *, lk, merge(1,0,flag)
   print *, selected_logical_kind(8), selected_logical_kind(16), &
      selected_logical_kind(32), selected_logical_kind(64)
   print *, selected_real_kind(6,37), selected_real_kind(7), &
      selected_real_kind(r=38), selected_real_kind(radix=2)
   print *, selected_int_kind(1000), selected_logical_kind(1000)
   print *, selected_real_kind(p=1000), selected_real_kind(r=10000), &
      selected_real_kind(p=1000,r=10000), selected_real_kind(radix=10)
end program
