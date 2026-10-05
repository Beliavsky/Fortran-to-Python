program vector_subscripts
   implicit none
   integer :: a(0:2,-1:2,4:8), i, j, k
   integer :: rows(2), columns(2), depths(3), empty(0)
   integer :: b(2,2,3), c(2,2), expected(2,2), mask(2,2)
   integer :: v(4), selectors(2)
   rows = [2,0]
   columns = [2,-1]
   depths = [8,4,6]
   do k = 4,8
      do j = -1,2
         do i = 0,2
            a(i,j,k) = i + 10*j + 100*k
         end do
      end do
   end do
   b = a(rows,columns,depths)
   if (any(shape(b) /= [2,2,3])) stop 1
   do k = 1,3
      do j = 1,2
         do i = 1,2
            if (b(i,j,k) /= a(rows(i),columns(j),depths(k))) stop 2
         end do
      end do
   end do
   print *, b
   print *, a(rows,columns,:)
   print *, a(:,columns,depths)
   print *, a(rows,:,depths)
   print *, a(rows,0,depths)
   print *, a(2:0:-1,0,depths)
   print *, size(a(empty,columns,:))
   print *, a([2,2,0],columns,4)
   expected = reshape([11,21,12,22], [2,2])
   a(rows,columns,4) = expected
   c = a(rows,columns,4)
   if (sum(abs(c - expected)) /= 0) stop 3
   mask = reshape([1,0,0,1], [2,2])
   where (mask == 1) a(rows,columns,4) = -9
   expected(1,1) = -9
   expected(2,2) = -9
   if (sum(abs(a(rows,columns,4) - expected)) /= 0) stop 4
   print *, a(rows,columns,4)
   a([2,0],[-1,2],5) = 7
   if (sum(abs(a(rows,columns,5) - 7)) /= 0) stop 5
   v = [1,2,3,4]
   selectors = [4,1]
   where ([.true.,.false.]) v(selectors) = -8
   print *, v
   print *, 'vector checks passed'
end program vector_subscripts
