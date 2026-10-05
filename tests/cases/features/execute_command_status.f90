program execute_command_status
   implicit none
   integer :: result, status, codes(2)
   character(len=12) :: message
   message = 'unchanged'
   print *, 'before'
   call execute_command_line('echo command_ok',.true.,result,status,message)
   print *, 'after'
   print *, result,status,trim(message)
   call execute_command_line(command='exit 7',cmdstat=status,exitstat=result)
   print *, result,status
   codes = -9
   call execute_command_line('exit 3',exitstat=codes(1),cmdstat=codes(2))
   print *, codes
   call execute_command_line('exit 0')
   call check_host()
   print *, result,status
contains
   subroutine check_host()
      call execute_command_line('exit 5',exitstat=result,cmdstat=status)
   end subroutine
end program
