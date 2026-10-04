module allocation_models
   implicit none
   type :: leaf
      integer :: values(2) = [2,4]
   end type leaf
   type :: holder
      real(kind=kind(1d0)), allocatable :: data(:)
   end type holder
end module allocation_models
program allocate_models
   use allocation_models
   implicit none
   real(kind=kind(1d0)) :: x(-1:1), matrix(0:1,-2:0)
   real(kind=kind(1d0)), allocatable :: y(:), z(:), v(:), a(:,:), b(:,:), scalar
   integer, allocatable :: counts(:), empty(:)
   complex(kind=kind(1d0)), allocatable :: complex_values(:)
   logical, allocatable :: flags(:)
   character(len=3), allocatable :: names(:)
   type(leaf), allocatable :: copies(:), defaults(:)
   type(holder) :: obj
   integer :: status,n
   character(len=80) :: message
   x = [10d0,20d0,30d0]
   matrix = reshape([1d0,2d0,3d0,4d0,5d0,6d0],[2,3])
   allocate(y,source=x)
   print *, y,lbound(y),ubound(y)
   y(-1) = 99d0
   print *, x(-1),y(-1)
   allocate(z,mold=x)
   print *, size(z),lbound(z),ubound(z)
   z = 7d0
   print *, z
   allocate(v,source=x(0:1))
   print *, v,lbound(v),ubound(v)
   allocate(a,source=matrix)
   allocate(b,mold=matrix)
   b = 8d0
   print *, a(0,-2),a(1,0),size(b),lbound(a),ubound(a)
   allocate(scalar,source=3.25d0)
   print *, scalar,merge(1,0,allocated(scalar))
   allocate(counts(2:4),source=5)
   print *, counts,lbound(counts),ubound(counts)
   deallocate(counts)
   n = 3
   allocate(counts(-2:n),mold=1)
   n = 20
   counts(-2) = 42
   print *, counts(-2),lbound(counts),ubound(counts)
   allocate(empty(5:3),source=1)
   print *, size(empty),lbound(empty),ubound(empty)
   allocate(complex_values,source=[(1d0,2d0),(-3d0,4d0)])
   print *, real(complex_values(2)),aimag(complex_values(2))
   allocate(flags,source=[.true.,.false.])
   print *, merge(1,0,flags(1)),merge(1,0,flags(2))
   allocate(names(2),source='ab ')
   print *, len(names(1)),len_trim(names(1))
   allocate(copies(2),source=leaf([7,9]))
   call modify(copies(1))
   print *, copies(1)%values(1),copies(2)%values(1)
   allocate(defaults(2),mold=leaf([99,99]))
   print *, defaults(1)%values(1),defaults(2)%values(2)
   allocate(obj%data,source=[1d0,2d0])
   print *, obj%data
   deallocate(v,z)
   allocate(v,z,source=[4d0,5d0],stat=status,errmsg=message)
   print *, status,v,z
   allocate(v(10),stat=status,errmsg=message)
   print *, merge(1,0,status/=0),size(v),merge(1,0,len_trim(message)>0)
   print *, v(1),lbound(v),ubound(v)
contains
   subroutine modify(value)
      type(leaf), intent(inout) :: value
      value%values(1) = 33
   end subroutine modify
end program allocate_models
