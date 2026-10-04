program formatted_file_io
   implicit none
   integer :: n
   real(kind=kind(1d0)) :: x
   open(unit=20, file='values.txt', status='replace', action='write')
   write(20,*) 7, 2.5d0
   close(20)
   open(unit=20, file='values.txt', status='old', action='read')
   read(20,*) n, x
   close(20)
   write(*,'(i3,1x,f8.3)') n, x
end program formatted_file_io
