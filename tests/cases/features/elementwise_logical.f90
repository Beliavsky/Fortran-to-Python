program elementwise_logical
   implicit none
   real(8) :: x(4)
   logical :: a(4), b(4), c(4), grid(2,2)
   integer :: i
   x = [-1d0, 0d0, 0.5d0, 1d0]
   a = x >= 0d0 .and. x < 1d0
   b = .not. (x < 0d0 .or. x >= 1d0)
   c = .true. .and. a .or. .false.
   do i = 1, 4
      print *, merge(1, 0, a(i)), merge(1, 0, b(i)), merge(1, 0, c(i))
   end do
   grid = reshape(a, [2,2])
   grid = .not. grid .or. .false.
   print *, count(grid), count(.not. grid)
   print *, merge(1, 0, all(x >= -1d0 .and. x <= 1d0))
   print *, merge(1, 0, any(.not. (x >= 0d0)))
   print *, merge(1, 0, .true. .or. .false. .and. .false.)
   print *, merge(1, 0, (.true. .or. .false.) .and. .false.)
   print *, merge(1, 0, .not. (.not. .true.))
   if (all(a .eqv. b) .and. .not. any(a .neqv. c)) print *, 42
   where (x >= 0d0 .and. x < 1d0) x = 9d0
   print *, x
end program elementwise_logical
