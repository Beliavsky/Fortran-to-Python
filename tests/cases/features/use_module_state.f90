module shared_state
   implicit none
   integer :: count = 0
   real :: values(-1:1)
   character(len=5) :: label
contains
   subroutine tick()
      call increment()
      values = values + 1.0
      label = 'ok'
   contains
      subroutine increment()
         count = count + 1
      end subroutine increment
   end subroutine tick
end module shared_state

program use_module_state
   use shared_state
   implicit none
   count = 10
   values = 2.0
   label = 'main'
   call tick()
   print *, count, values(-1), values(1), label
   call internal_tick()
   print *, count
   block
      integer :: count
      count = 99
      print *, count
   end block
   print *, count
contains
   subroutine internal_tick()
      count = count + 2
      call nested_tick()
   end subroutine internal_tick
   subroutine nested_tick()
      count = count + 3
   end subroutine nested_tick
end program use_module_state
