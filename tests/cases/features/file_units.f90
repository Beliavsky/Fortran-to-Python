program file_units
   implicit none
   integer :: first, second, ios, x(3), matrix(2,2), n
   logical :: ok
   real(kind=kind(1d0)) :: value
   character(len=8) :: text
   character(len=100) :: message

   open(newunit=first, status='scratch', action='readwrite')
   open(newunit=second, status='scratch')
   print *, first < 0, second < 0, first /= second
   call put_values(first)
   rewind(unit=first)
   read(unit=first, fmt=*, iostat=ios) x
   print *, ios, x
   write(second,*) 1, 2
   write(second,*) 3, 4
   rewind second
   read(second,*) matrix
   print *, matrix
   read(second,*,iostat=ios) n
   print *, ios < 0
   close(first)
   close(second)

   open(unit=20, file='file_units_values.txt', status='replace', action='write')
   write(unit=20, fmt=*) 7, 2.5d0, .true.
   close(unit=20)
   open(unit=20, file='file_units_values.txt', status='old', action='read')
   read(20,*) n, value, ok
   print *, n, value, ok
   close(20, status='delete')
   open(unit=21, file='file_units_values.txt', status='old', iostat=ios, iomsg=message)
   print *, ios /= 0, len_trim(message) > 0

   open(newunit=first, status='scratch')
   write(first,'(a)') 'hello'
   rewind(first)
   read(first,'(a)',iostat=ios) text
   print *, ios, len(text), len_trim(text), trim(text) == 'hello'
   read(first,'(a)',iostat=ios) text
   print *, ios < 0, trim(text) == 'hello'
   close(first)
contains
   subroutine put_values(unit)
      integer, intent(in) :: unit
      write(unit,*) 10, 20, 30
   end subroutine
end program
