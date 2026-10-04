program logical_masks
   implicit none
   integer :: a(4)
   logical :: mask(4)
   a = [-2, 0, 3, 5]
   mask = a > 0
   where (mask) a = a * 2
   print *, count(mask), sum(a, mask=mask), sum(a)
   print *, merge(1, 0, all(mask)), merge(1, 0, any(mask))
end program logical_masks
