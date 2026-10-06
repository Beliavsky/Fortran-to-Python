program logical_kind_literals
implicit none
integer, parameter :: lk=8
logical(1) :: a=.true._1
logical(8) :: b=.false._lk, v(3)
v=[.true._lk,.false._lk,.TRUE._8]
print *,a,b,v
print *,kind(.true._1),kind(.false._lk),kind(v)
print *, .not. .false._8, .true._1 .and. .false._1
print '(a)', '.true._lk stays literal text'
end program
