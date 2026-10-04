program logical_equivalence
   implicit none
   logical :: a(4), b(4), c(4), d(4)
   integer :: i
   a = [.false.,.false.,.true.,.true.]
   b = [.false.,.true.,.false.,.true.]
   c = a .eqv. b
   d = a .neqv. b
   do i = 1,4
      print *, merge(1,0,c(i)), merge(1,0,d(i))
   end do
   print *, merge(1,0,(.true. .eqv. .false.)), merge(1,0,(.true. .neqv. .false.))
end program logical_equivalence
