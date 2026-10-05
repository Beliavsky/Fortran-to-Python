module integer_models
   use iso_fortran_env, only: int16,int32,int64
   implicit none
   integer(int16) :: host_value
   type :: payload
      integer(int32) :: small
      integer(int64) :: large
   end type
contains
   subroutine show_models(dummy)
      integer(int16), intent(in) :: dummy
      print *, huge(dummy), digits(dummy), range(dummy), radix(dummy)
      print *, huge(host_value)
   end subroutine
end module

program integer_model_kinds
   use iso_fortran_env, only: int8,int16,int32,int64,wide=>int64
   use integer_models
   implicit none
   integer :: ordinary
   integer*4 :: legacy_small
   integer*8 :: legacy_large
   integer(int8) :: byte
   integer(kind=int16) :: short
   integer(int32) :: word
   integer(wide) :: long
   integer, parameter :: k = int64
   integer(k) :: by_parameter
   integer(int16) :: values(0:2)
   integer(int64), allocatable :: unallocated(:)
   type(payload) :: p, objects(2)
   print *, huge(ordinary), huge(legacy_small), huge(legacy_large)
   print *, huge(byte), huge(short), huge(word), huge(long), huge(by_parameter)
   print *, digits(byte), digits(short), digits(word), digits(long)
   print *, range(byte), range(short), range(word), range(long)
   print *, radix(byte), radix(short), radix(word), radix(long)
   print *, huge(values), huge(values(0)), huge(unallocated)
   print *, huge(p%small), huge(p%large)
   print *, huge(objects(1)%small), huge(objects(2)%large)
   print *, huge(0), huge(0_int8), huge(0_int16), huge(0_int32), huge(0_int64)
   print *, huge(x=0_int16), huge(1_8)
   ! These model inquiries must not evaluate the argument value.
   print *, huge(long+1), huge(1_int64+ordinary), huge(-long), huge(short**2)
   print *, huge(short**2_int16), huge(long/2)
   call show_models(0_int16)
   call check_local()
   print *, 'integer model checks passed'
contains
   subroutine check_local()
      integer(int8) :: ordinary
      print *, huge(ordinary), huge(long)
   end subroutine
end program
