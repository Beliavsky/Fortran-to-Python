module initialized_components
   implicit none
   integer, parameter :: seed(3) = [2,4,6]
   type :: leaf
      integer :: id = 7
      integer :: values(2) = [1,2]
      integer :: ranged(-1:0) = [8,9]
      integer :: matrix(0:1,-1:0) = reshape([1,2,3,4],[2,2])
   end type leaf
   type :: record
      integer :: numbers(3) = seed
      real(kind=kind(1d0)) :: fractions(2) = [1.25d0,-2.5d0]
      real(kind=kind(1d0)) :: grid(2,3) = 1.5d0
      integer :: matrix(2,3) = reshape([1,2,3,4,5,6],[2,3])
      logical :: flags(2) = [.true.,.false.]
      complex(kind=kind(1d0)) :: z(2) = [(1d0,2d0),(-3d0,4d0)]
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
   type(leaf) :: rows(-1:0)
   complex(kind=kind(1d0)) :: q(2)
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
   print *, a%defaults(2)%values(2),a%copies(2)%values(2)
   print *, a%copies(1)%ranged(-1),a%copies(1)%ranged(0)
   print *, a%copies(1)%matrix(0,-1),a%copies(1)%matrix(1,0)
   a%numbers(1) = 99
   call change_leaf(a%copies(1))
   print *, b%numbers(1),a%copies(1)%id,a%copies(2)%id,b%copies(1)%id
   print *, a%copies(1)%values(1),a%copies(2)%values(1),b%copies(1)%values(1)
   a%copies(1)%values(1) = 1.9d0
   a%copies(1)%values(2:1:-1) = [4.9d0,-2.9d0]
   print *, a%copies(1)%values(1),a%copies(1)%values(2)
   a%copies(1)%values = 6
   print *, a%copies(1)%values(1),a%copies(1)%values(2)
   a%copies(1)%ranged(0:-1:-1) = [12,13]
   a%copies(1)%matrix(0,-1) = 17
   print *, a%copies(1)%ranged(-1),a%copies(1)%ranged(0),a%copies(1)%matrix(0,-1)
   where ([.true.,.false.])
      a%copies(1)%values = [2.9d0,3.9d0]
   end where
   print *, a%copies(1)%values(1),a%copies(1)%values(2)
   rows(-1) = leaf(21,[5,6])
   rows(0) = leaf(22,[7,8])
   rows(0)%values(1) = 55
   print *, rows(-1)%values(2),rows(0)%values(1),rows(0)%matrix(0,-1)
   q = [(1d0,2d0)+(3d0,4d0),conjg((5d0,6d0))]
   call show_z(q)
   call show_z(values=[(7d0,8d0),(-9d0,10d0)])
contains
   subroutine show_z(values)
      complex(kind=kind(1d0)), intent(in) :: values(2)
      print *, real(values(1)),aimag(values(1)),real(values(2)),aimag(values(2))
   end subroutine show_z
   subroutine change_leaf(value)
      type(leaf), intent(inout) :: value
      value%id = 20
      value%values(1) = 30
   end subroutine change_leaf
end program array_component_initializers
