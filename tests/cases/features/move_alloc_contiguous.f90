program move_alloc_contiguous
   implicit none
   integer, allocatable :: a(:), b(:)
   integer :: values(8)
   integer :: i, stat
   allocate(a(-2:1))
   a = [10,20,30,40]
   b = [99]
   call move_alloc(from=a, to=b, stat=stat)
   print *, stat, merge(1,0,allocated(a)), merge(1,0,allocated(b))
   print *, lbound(b), ubound(b), b(-2), b(1)
   allocate(a(2))
   a = [7,8]
   print *, lbound(b), ubound(b), b(-2)
   call move_alloc(a,b)
   print *, b, merge(1,0,allocated(a))
   call move_alloc(a,b)
   print *, merge(1,0,allocated(b))
   values = [(i,i=1,8)]
   print *, merge(1,0,is_contiguous(values)), merge(1,0,is_contiguous(values(1:8:2)))
   call inspect(values(1:8:2))
   call update(values(1:8:2))
   print *, values
   print *, inquire(values(1:8:2))
contains
   subroutine inspect(x)
      integer, intent(in), contiguous :: x(:)
      print *, size(x), merge(1,0,is_contiguous(x)), sum(x)
   end subroutine
   subroutine update(x)
      integer, intent(inout), contiguous :: x(:)
      print *, merge(1,0,is_contiguous(x))
      x = x + 10
   end subroutine
   integer function inquire(x)
      integer, intent(in), contiguous :: x(:)
      inquire = merge(1,0,is_contiguous(x))
   end function
end program move_alloc_contiguous
