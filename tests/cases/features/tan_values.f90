program tan_values
implicit none
real(8) :: x(4)
x = [0d0, 0.125d0, -0.25d0, 1d0]
print *, tan(0.0)
print *, tan(x)
print *, tan(0.5d0)
print *, 'tan(0.0)'
end program tan_values
