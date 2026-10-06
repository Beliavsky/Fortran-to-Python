program unlimited_format_items
implicit none
integer :: v(3)=[2,3,4], a(2,2), empty(0)
character(len=80) :: record
a=reshape([1,2,3,4],[2,2])
print '(*(1x,i0))', 1,v,5
print '(a,*(1x,i0))', 'matrix',0,a,5
print '(*(i0,:,","))',1,v,5
print '(*(i0,1x,i0,:,";"))',1,2,3,4,5
print '(*(2(i0,:,",")))',1,2,3,4,5
print '(*(i0,:,","))',empty
write(*,'(*(i0,:,":"))')1,v,5
write(record,'(*(i0,:,","))')1,v,5
print '(a)',trim(record)
end program
