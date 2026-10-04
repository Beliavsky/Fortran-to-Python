module initialized_components
   implicit none
   integer, parameter :: seed(3) = [2,4,6]
   type :: leaf
      integer :: id = 7
      integer :: values(2) = [1,2]
   end type leaf
   type :: record
      integer :: numbers(3) = seed
      real(kind=kind(1d0)) :: fractions(2) = [1.25d0,-2.5d0]
      real(kind=kind(1d0)) :: grid(2,3) = 1.5d0
      integer :: matrix(2,3) = reshape([1,2,3,4,5,6],[2,3])
      logical :: flags(2) = [.true.,.false.]
      complex(kind=kind(1d0)) :: z(2) = (1d0,2d0)
      character(len=3) :: names(2) = ['a  ','bc ']
      character(len=3) :: repeated(2) = 'longer'
      integer :: empty(0) = 3
      type(leaf) :: defaults(2)
      type(leaf) :: copies(2) = leaf(10,[3,4])
   end type record
end module initialized_components
program array_component_initializers
   use initialized_components
   implicit none
   type(record) :: a,b
   integer :: i,j
   print *, a%numbers
   print *, a%fractions
   do j = 1,3
      do i = 1,2
         print *, a%grid(i,j), a%matrix(i,j)
      end do
   end do
   print *, merge(1,0,a%flags(1)),merge(1,0,a%flags(2))
   print *, real(a%z(1)),aimag(a%z(1)),real(a%z(2)),aimag(a%z(2))
   print *, len(a%names(1)),len_trim(a%names(1)),len_trim(a%names(2))
   print *, a%repeated(1),size(a%empty)
   print *, a%defaults(1)%id,a%copies(1)%id
   call show_values(a%defaults(2))
   call show_values(a%copies(2))
   a%numbers(1) = 99
   call change_leaf(a%copies(1))
   print *, b%numbers(1),a%copies(1)%id,a%copies(2)%id,b%copies(1)%id
   call show_values(a%copies(1))
   call show_values(a%copies(2))
   call show_values(b%copies(1))
contains
   subroutine show_values(value)
      type(leaf), intent(in) :: value
      print *, value%values(1),value%values(2)
   end subroutine show_values
   subroutine change_leaf(value)
      type(leaf), intent(inout) :: value
      value%id = 20
      value%values(1) = 30
   end subroutine change_leaf
end program array_component_initializers
