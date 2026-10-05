program forall_semantics
implicit none
integer :: i,j,a(8),b(8),m(2,2)
a=[1,2,3,4,5,6,7,8]
forall(i=2:8)
a(i)=a(i-1)
end forall
print *, a
do i=2,8
a(i)=a(i-1)
end do
print *, a
a=[1,2,3,4,5,6,7,8]
b=0
forall(i=1:8,a(i)>4)
a(i)=-a(i)
b(i)=a(i)*10
end forall
print *, a,b
i=99
j=88
m=reshape([1,2,3,4],[2,2])
forall(i=1:2,j=1:2) m(i,j)=m(j,i)
print *, m,i,j
forall(i=1:2) m(:,i)=m(:,3-i)
print *, m
a=[2,3,4,5,6,7,8,1]
forall(i=1:8) a(a(i))=i
print *, a
a=[1,2,3,4,5,6,7,8]
forall(i=8:2:-1) a(i)=a(i-1)
forall(i=8:1) a(i)=99
print *, a
end program
