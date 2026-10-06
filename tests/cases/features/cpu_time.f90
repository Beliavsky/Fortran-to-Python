program main
implicit none
type :: timer
real :: value
real :: samples(2)
real, pointer :: alias => null()
end type
type(timer) :: record, records(2)
real :: t0, t1, t(2), matrix(2,2), via_dummy
real, target :: target
real, pointer :: p
double precision :: wide
call cpu_time(t0)
call cpu_time(time=t1)
print *, t0 >= 0.0, t1 >= t0
call cpu_time(t(1))
call cpu_time(t(2))
print *, t(1) >= 0.0, t(2) >= t(1)
call cpu_time(record%value)
call cpu_time(record%samples(1))
call cpu_time(records(2)%value)
call cpu_time(matrix(1,2))
print *, record%value >= 0.0, record%samples(1) >= 0.0, records(2)%value >= 0.0, matrix(1,2) >= 0.0
call stamp(via_dummy)
print *, via_dummy >= 0.0
p => target
call cpu_time(p)
call cpu_time(wide)
print *, target >= 0.0, wide >= 0.0d0
record%alias => target
call cpu_time(record%alias)
print *, associated(record%alias,target), target == record%alias
print *, 'call cpu_time(t0)'
contains
subroutine stamp(value)
real :: value
call cpu_time(time=value)
end subroutine
end program
