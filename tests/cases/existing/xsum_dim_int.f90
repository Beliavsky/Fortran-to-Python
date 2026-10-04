use iso_fortran_env
implicit none
integer, parameter :: ikind=int32
integer(kind=ikind), allocatable :: y(:,:)
integer, parameter :: n1 = 3, n2 = 5
integer :: i1, i2
allocate (y(n1,n2))

do i1=1,n1
   do i2=1,n2
      y(i1,i2) = i1 + 10*i2
   end do
end do
print*,y
print*,sum(y)
print*,sum(y,1)
print*,sum(y,2)
end
