program strings
   implicit none
   character(len=12) :: text
   text = 'hello'
   print *, trim(text) // '_world'
   print *, len(text), len_trim(text), index(text, 'll')
   print *, text(2:4)
end program strings
