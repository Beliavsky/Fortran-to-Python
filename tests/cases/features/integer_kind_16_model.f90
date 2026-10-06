program integer_kind_16_model
implicit none
integer(1) a1,b1
integer(2) a2,b2
integer(4) a,b
integer(8) c,d
integer(16) e,f
integer(16), allocatable :: unallocated(:)
a=10
b=20
c=30
d=40
e=50
f=60
print *,kind(e),kind(0_16),digits(e),range(e),radix(e)
print '(i0)',huge(e)
print '(i0)',huge(unallocated)
print '(*(i0,:," "))',a,b,c,d,e,f,kind(a),kind(b),kind(c),kind(d),kind(e),kind(f)
print '(*(i0,:," "))',huge(a1),huge(b1),huge(a2),huge(b2),huge(a),huge(b),huge(c),huge(d),huge(e),huge(f)
end program
