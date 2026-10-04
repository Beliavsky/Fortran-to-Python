program additional_intrinsics
   use iso_fortran_env, only: int64
   implicit none
   integer :: x(4), matrix(2,3), field(2,2)
   integer :: neg
   integer(int64) :: wide
   logical :: mask(2,2)
   character(len=8) :: text
   character(len=3) :: words(2)
   character(len=4) :: arg
   integer :: n, stat
   x = [1,2,3,4]
   matrix = reshape([1,2,3,4,5,6], [2,3])
   print *, product(x), product(x, .false.), product(x, mask=x>2)
   print *, product(array=matrix, dim=1), product(matrix, dim=2)
   print *, product(x(1:0)), product(matrix, dim=1, mask=.false.)
   mask = reshape([.true.,.false.,.true.,.true.], [2,2])
   field = reshape([1,2,3,4], [2,2])
   print *, unpack(vector=[10,20,30,99], mask=mask, field=field)
   print *, unpack([10,20,30], mask, -1)
   print *, cshift(x, 1), cshift(x, -1), eoshift(x, 1, boundary=-1)
   print *, cshift(matrix, shift=[1,-1], dim=2)
   print *, eoshift(matrix, dim=2, shift=[1,-1], boundary=[9,8])
   print *, eoshift(x, 5), eoshift(x, -5)
   print *, spread(x, dim=1, ncopies=2)
   text = '  ab  '
   print *, adjustr(string=text)
   print *, scan('banana','an'), scan('banana','an', back=.true.)
   print *, verify('123x5','0123456789'), verify('xx123x','0123456789', back=.true.)
   print *, scan('banana','an',kind=int64), repeat('a ',2)
   words = ['ab ', ' c ']
   print *, adjustr(words)
   neg = -1
   print *, merge(1,0,btest(neg,31)), shiftr(neg,31), shiftl(1,31), ibclr(neg,31)
   print *, ibits(10,1,2), iand(12,10), ior(12,10), ieor(12,10), ibset(10,0)
   print *, ibset([10,12], 0), shiftr([16,32], [2,3])
   wide = -1
   print *, merge(1,0,btest(wide,63)), shiftr(wide,63), ibclr(wide,63)
   print *, shiftr(-1_8,63)
   print *, command_argument_count()
   call get_command_argument(number=1, value=arg, length=n, status=stat)
   print *, len_trim(arg), n, merge(1,0,stat>0)
end program additional_intrinsics
