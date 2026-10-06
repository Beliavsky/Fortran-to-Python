program character_lengths
implicit none
integer, parameter :: n=5
character*5 :: a='hi'
character*((n+1)/2) :: b
character(len=(n+1)/2) :: modern
character*(3) :: old_array(2)
character(len=3) :: modern_array(2)
b='abcdef'
modern='x'
print *, len(a), '['//a//']'
print *, len(b), '['//b//']'
print *, len(modern), '['//modern//']'
modern='123456'
print *, len(modern), '['//modern//']'
old_array=['abcdef', 'x     ']
modern_array=['abcdef', 'x     ']
print *, len(old_array), '['//old_array(1)//'] ['//old_array(2)//']'
print *, len(modern_array), '['//modern_array(1)//'] ['//modern_array(2)//']'
call shorten(b)
print *, len(b), '['//b//']'
contains
subroutine shorten(text)
character*(*), intent(inout) :: text
text='x'
end subroutine
end program
