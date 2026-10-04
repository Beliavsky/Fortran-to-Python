program execute_command_line_test
   implicit none
   integer :: exit_status,command_status
   call execute_command_line('echo command_ok',wait=.true.,exitstat=exit_status,cmdstat=command_status)
   print *, exit_status,command_status
end program execute_command_line_test
