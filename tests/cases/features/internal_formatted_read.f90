program internal_formatted_read
implicit none
character(len=10) :: text
character(len=40) :: message
character(len=3) :: word
integer :: year, month, day, ios, n
real(kind=kind(1.0d0)) :: x
logical :: flag
text = '2002-07-30'
read(text, '(i4,1x,i2,1x,i2)') year, month, day
print *, year, month, day
text = '2002,07,30'
read(text, *) year, month, day
print *, year, month, day
text = '2020 12 31'
read(text, *) year, month, day
print *, year, month, day
text = '001250'
read(unit=text, fmt='(f6.2)') x
print *, x
text = '1.25D+02'
read(text, '(d8.2)') x
print *, x
text = '123E+02'
read(text, '(e7.2)') x
print *, x
text = '1.2+003'
read(text, '(g7.2)') x
print *, x
text = '.false.'
read(text, '(l7)') flag
print *, flag
text = 'abcdef'
read(text, '(a6)') word
print *, word
text = '1234'
read(text, '(3i2)') year, month, day
print *, year, month, day
text = 'oops'
n = 42
read(text, '(i4)', iostat=ios, iomsg=message) n
print *, ios > 0, len_trim(message) > 0, n
end program
