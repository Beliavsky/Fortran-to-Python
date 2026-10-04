module extension_module
   implicit none
   type :: base
      integer :: id
   end type base
   type, extends(base) :: child
      integer :: extra
   end type child
end module extension_module
program type_extension
   use extension_module
   implicit none
   type(child) :: value
   value%id = 3
   value%extra = 8
   print *, value%id,value%extra,value%base%id
end program type_extension
