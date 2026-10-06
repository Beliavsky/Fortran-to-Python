program main
use iso_fortran_env, only: int8, int16, int32, int64
implicit none
type :: box
integer(int64) :: i
end type
type(box) :: b
integer(int16) :: a(2)
integer(16) :: wide
integer, allocatable :: absent(:)
integer :: calls = 0
a = [1,2]
print *, bit_size(0), bit_size(0_int8), bit_size(0_int16), bit_size(0_int32), bit_size(0_int64)
print *, bit_size(a(1)), bit_size(-a(2)), bit_size(a(1)**2), bit_size(a(1)+1)
print *, bit_size(a(1)**2_int16), kind(a(1)**2), kind(1.0_int64**2)
print *, bit_size(huge(0_int8)), bit_size(huge(0_int64)), bit_size(wide), bit_size(0_16)
print *, bit_size(i=0_int64), bit_size(bit_size(0_int8)), kind(bit_size(0_int64))
print *, bit_size(b%i)
print *, huge(bit_size(0_int8)), huge(bit_size(0_int16))
print *, bit_size(absent(1)), bit_size(side_effect()), calls
print *, 'bit_size(0_int64)'
contains
integer(int64) function side_effect()
calls = calls + 1
side_effect = 0
end function
end program
