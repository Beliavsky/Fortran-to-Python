module rank_specification
   implicit none
   integer :: matrix(2, 3)
   integer, parameter :: known_rank = rank(matrix)
end module rank_specification

program shape_rank
   use iso_fortran_env, only: int64
   use rank_specification, only: known_rank
   implicit none
   integer :: a(-1:1, 0:1), b(0, 3), c(2, 3)
   real, allocatable :: unallocated(:, :), scalar
   integer, parameter :: r = rank(unallocated)
   a = 7
   print *, shape(source=a, kind=int64)
   print *, shape(a, 8)
   print *, rank(a=a)
   print *, shape(a(-1:1:2, :))
   print *, rank(a(:, 0))
   print *, shape(b), rank(b)
   print *, size(shape(7)), rank(7), rank('text')
   print *, rank(unallocated), rank(scalar)
   print *, r
   print *, known_rank
   c = reshape([1, 2, 3, 4, 5, 6], shape(c), order=[2, 1])
   print *, c
   call show(c)
   call describe(7)
   call describe(c)
contains
   subroutine show(x)
      integer, intent(in) :: x(:, :)
      print *, rank(x), shape(x), size(x), sum(x)
   end subroutine show
   subroutine describe(x)
      integer, intent(in) :: x(..)
      print *, rank(x), size(shape(x))
   end subroutine describe
end program shape_rank
