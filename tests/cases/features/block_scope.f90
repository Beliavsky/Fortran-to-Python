program block_scope
   implicit none
   integer :: x, n
   x = 10
   block
      integer :: x
      x = 20
      block
         integer :: x
         x = 30
         print *, x
      end block
      print *, x
   end block
   sibling: block
      real :: x
      x = 2.5
      print *, x
   end block sibling
   print *, x
   do n = 1, 3
      block
         integer :: a(n)
         a = n
         print *, size(a), sum(a)
      end block
   end do
end program block_scope
