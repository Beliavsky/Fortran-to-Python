program string_assignment
   implicit none
   character(len=5) :: s, a(3)
   character(len=0) :: empty
   character(len=3) :: initialized = 'abcdef'
   integer :: i
   s = 'hi'
   print *, len(s), len_trim(s), index(s,'   ')
   s = 'abcdefgh'
   print *, s, len_trim(s)
   s = '  xy'
   print *, trim(adjustl(s)), len(adjustl(s)), len_trim(adjustl(s))
   print *, index('banana','an'), index('banana','an',back=.true.)
   print *, index(substring='x',string=s), index('abc','',.true.)
   a = 'q'
   a(2) = 'abcdefg'
   a(3) = '  z'
   do i = 1,3
      print *, trim(a(i)), len(a(i)), len_trim(a(i))
   end do
   a(1:2) = 'longer'
   print *, trim(a(1)), trim(a(2))
   a = ['x  ','yy ','zzz']
   print *, len(a), len_trim(a(1)), len_trim(a(2)), len_trim(a(3))
   print *, initialized, len(initialized)
   empty = 'discard'
   print *, len(empty), len_trim(empty)
end program string_assignment
