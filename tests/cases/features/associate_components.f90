program associate_components
implicit none
type :: item
integer :: v(4), m(2,2), offset(-1:2)
end type
type(item), target :: x,y
integer :: i,a(0:1)
x%v=[1,2,3,4]
associate(p=>x%v(2:4:2))
p=p*10
end associate
print *, x%v
associate(p=>x%v)
p=2.9
end associate
print *, x%v
x%v=[1,2,3,4]
associate(p=>x%v(3))
p=p*10
end associate
print *, x%v
x%m=reshape([1,2,3,4],[2,2])
associate(p=>x%m(2,1), q=>x%m(:,2))
p=20
q=q*10
end associate
print *, x%m
x%offset=[1,2,3,4]
associate(p=>x%offset(0:2:2), q=>x%offset(-1))
p=p*10
q=9
end associate
print *, x%offset
x%v=[1,2,3,4]
associate(p=>x%v*2)
x%v=[9,9,9,9]
print *, p
end associate
print *, x%v
x%v=[1,2,3,4]
y%v=[5,6,7,8]
associate(p=>x%v(2:4:2))
associate(p=>y%v(1:3:2))
p=p*10
end associate
p=p*100
end associate
print *, x%v,y%v
a=[7,8]
associate(a=>x%v(2:4:2))
a(1)=20
end associate
a(0)=70
print *, x%v,a
x%v=[1,2,3,4]
associate(x=>x%v(1:2), p=>x%v(3:4))
x=x*10
p=p*100
end associate
print *, x%v
associate(p=>x%v*2)
x%v=[9,9,9,9]
print *, p(1),p(4)
end associate
end program
