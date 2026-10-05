program where_semantics
implicit none
integer :: v(4)
logical :: mask(4), result(4)
v=[10,20,30,40]
region: where(v<25)
v=10*v
else where region
v=-1
end where region
print *, v
mask=[.true.,.false.,.true.,.false.]
result=.false.
where(mask)
mask=.false.
result=.true.
elsewhere
result=.false.
end where
print *, mask,result
v=[1,2,3,4]
branches: where(v<2)
v=10
else where(v<4) branches
v=20
elsewhere branches
v=-1
endwhere branches
print *, v
v=[-2,-1,1,2]
outer: where(v<0)
inner: where(v<-1)
v=100
elsewhere inner
v=200
end where inner
elsewhere outer
v=-1
endwhere outer
print *, v
v=[1,2,3,4]
where(v<3) v=10*v
print *, v
end program
