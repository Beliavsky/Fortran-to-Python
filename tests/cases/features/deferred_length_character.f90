program deferred_length_character
   implicit none
   type text_box
      character(:), allocatable :: text
   end type
   type(text_box) :: box
   character(:), allocatable :: s, t
   character(len=8) :: fixed

   print *, merge(1, 0, allocated(s))
   s = 'modern'
   t = s // ' Fortran'
   print *, len(s), s
   print *, len(t), t
   s = repeat('ab', 4)
   print *, len(s), s
   s = 'x '
   print *, len(s), len_trim(s)
   s = ''
   print *, len(s), merge(1, 0, allocated(s))
   fixed = 'abc'
   s = fixed
   print *, len(s), len_trim(s)
   fixed = 'abcdefghijkl'
   s = fixed
   print *, len(s), s
   box%text = 'box'
   box%text = box%text // ' expanded'
   print *, len(box%text), box%text
   deallocate(s)
   print *, merge(1, 0, allocated(s))
   s = 'again'
   print *, len(s), s
   call saved_text()
   call saved_text()
contains
   subroutine saved_text()
      character(:), allocatable, save :: text
      if (.not. allocated(text)) text = ''
      text = text // 'a'
      print *, len(text), text
   end subroutine
end program
