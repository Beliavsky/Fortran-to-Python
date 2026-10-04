program derived_type_array_components
implicit none
type dt
   integer :: v, w
end type
type(dt) :: x(3), a(2,2)
x%v = [10, 20, 30]
x%w = [100, 200, 300]
print *, x
print *, x%v
print *, pack(x%w, x%v > 10)
print *, sum(x%w)
a%v = reshape([1,2,3,4], [2,2])
a%w = 10 * a%v
where (a%v > 2)
   a%w = a%w + 1
end where
print *, a
print *, pack(a%w, a%v > 1)
end program
