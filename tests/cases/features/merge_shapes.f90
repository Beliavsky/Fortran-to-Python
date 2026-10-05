program merge_shapes
   implicit none
   integer :: v(3) = [4, 9, 16], w(3) = [100, 200, 300]
   integer :: matrix(2,3), cube(2,1,3), empty(0)
   logical :: flags(3) = [.true., .false., .true.]
   real(8) :: reals(2) = [1.5d0, 2.5d0]
   complex(8) :: z(2) = [(1d0,2d0), (3d0,4d0)]
   character(len=4) :: words(2) = ['abcd', 'efgh']
   print *, merge(10, 20, v > 5)
   print *, merge(10, w, v > 5)
   print *, merge(10, w, .true.)
   print *, merge(10, w, .false.)
   print *, merge(w, 10*w, v > 5)
   print *, merge(w, 10, .true.)
   print *, merge(w, 10, .false.)
   matrix = reshape([1,2,3,4,5,6], [2,3])
   cube = reshape([1,2,3,4,5,6], [2,1,3])
   print *, merge(10, matrix, .true.)
   print *, merge(matrix, 10, .false.)
   print *, merge(10, cube, .true.)
   print *, merge(cube, 10, .false.)
   print *, size(merge(10, empty, .true.))
   print *, size(merge(empty, 10, .false.))
   print *, merge(1, 2, .true.), merge(1, 2, .false.)
   print *, merge(5.5d0, reals, .true.)
   print *, merge(reals, 5.5d0, .false.)
   print *, count(merge(.false., flags, .true.))
   print *, count(merge(flags, .true., .false.))
   print *, real(merge((5d0,6d0), z, .true.)), aimag(merge(z, (5d0,6d0), .false.))
   print *, merge('ijkl', words, .true.)
   print *, merge(words, 'ijkl', .false.)
end program merge_shapes
