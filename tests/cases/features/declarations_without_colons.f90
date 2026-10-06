program declarations_without_colons
implicit none
integer(1) i1
integer(8) i8,j8
integer(16) i16
real x(3)
real(kind=8) y(-1:1)
double precision d
complex z
double complex zz
logical flag
character*3 text
character(len=4) word
integer integer,real
i1=2
i8=30
j8=40
x=[1.0,2.0,3.0]
y=[4.0d0,5.0d0,6.0d0]
d=7.0d0
z=(1.0,2.0)
zz=(3.0d0,4.0d0)
flag=.true.
text='abcdef'
word='hello'
integer=11
real=12
print *, kind(i1), kind(i8), i1, i8+j8
print *, kind(i16), huge(i8)
print *, kind(x), kind(y), kind(d), kind(z), kind(zz)
print *, lbound(y,1), ubound(y,1), int(y(-1)), int(y(1))
print *, flag
print *, text
print *, word
print *, len(text), len(word)
print *, integer, real
call report(i8,x,zz,text)
contains
subroutine report(i,v,c,s)
integer(8) i
real v(3)
double complex c
character*(*) s
print *, kind(i), kind(v), kind(c), len(s)
end subroutine
end program
