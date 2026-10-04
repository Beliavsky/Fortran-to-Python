program named_loop_control
   implicit none
   integer :: i, j, k, total
   total = 0
   outer: do i = 1, 5
      inner: do j = 1, 5
         if (j == 2) cycle inner
         if (i*j > 12) exit outer
         total = total + i*j
      end do inner
   end do outer
   print *, total, i, j

   total = 0
   rounds: do i = 1, 4
      middle: do j = 1, 3
         do k = 1, 3
            if (k == 2) cycle ROUNDS
            total = total + i
         end do
      end do middle
      total = total + 100
   end do rounds
   print *, total, i, j, k

   i = 0
   total = 0
   again: do while (i < 3)
      i = i + 1
      do j = 1, 3
         if (j == 2) cycle again
         total = total + i
      end do
   end do again
   print *, total, i, j

   i = 0
   forever: do
      i = i + 1
      do j = 1, 3
         if (i == 2) exit forever
      end do
   end do forever
   print *, i, j

   total = 0
   down: do i = 3, 1, -1
      if (i == 2) cycle down
      total = total + i
   end do down
   print *, total, i

   empty: do i = 1, 0
   end do empty
   print *, i
end program named_loop_control
