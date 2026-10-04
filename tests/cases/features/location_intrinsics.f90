program location_intrinsics
implicit none
integer :: v(-2:2), a(0:1,-1:1), empty(0), zero_rows(0,3)
logical :: mask(2,3)
character(len=2) :: words(3)
v = [2,4,6,-1,4]
a = reshape([4,1,1,6,6,1], [2,3])
mask = reshape([.true.,.false.,.true.,.true.,.false.,.true.], [2,3])
words = ['a ', 'b ', 'a ']
print *, minloc(v), maxloc(v)
print *, findloc(v,4), findloc(v,4,back=.true.), findloc(v,5)
print *, minloc(a), minloc(a,back=.true.), maxloc(a)
print *, minloc(a,dim=1), maxloc(a,dim=2)
print *, findloc(a,6,dim=1), findloc(a,1,dim=2,back=.true.)
print *, minloc(a,mask=mask), maxloc(a,1,mask,kind=8)
print *, findloc(a,1,mask=mask,kind=8,back=.true.)
print *, minloc(v,mask=.false.), findloc(empty,1), maxloc(zero_rows,dim=1)
print *, minloc(v,dim=1), findloc(words,'a'), findloc(words,'a',back=.true.)
print *, findloc([.false.,.true.,.true.],.true.,back=.true.)
print *, minloc(words,back=.true.), maxloc(words)
end program
