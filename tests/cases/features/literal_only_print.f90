program literal_only_print
implicit none
print "('hello')"
print "(a)", new_line('a')
print "('world',a)", new_line('a')
print "('bye')"
print '("quoted")'
print "(2x,'hi',/,2('x',1x))"
print "('prefix',:,'suffix')"
print "('prefix',i4,'suffix')"
print "()"
print "(/)"
print "('don''t')"
print '("a""b")'
if (.true.) print "('yes')"
if (.false.) print "('no')"
end program
