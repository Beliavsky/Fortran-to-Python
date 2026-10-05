module extension_components
   implicit none
   type :: base
      integer :: id = 1
      integer :: samples(2) = [2,4]
   end type
   type, extends(base) :: child
      integer :: extra = 8
   end type
   type, extends(child) :: leaf
      integer :: tip = 9
   end type
end module
program type_extension_components
   use extension_components
   implicit none
   type(child) :: a, b, records(2)
   type(base) :: snapshot
   type(leaf) :: last
   a%id = 3
   a%base%samples(1) = 10
   a%samples(2) = 20
   print *, a%id,a%base%id,a%samples,a%base%samples
   a%base%id = 7
   snapshot = a%base
   snapshot%id = 11
   snapshot%samples(1) = 30
   print *, a%id,snapshot%id,a%samples,snapshot%samples
   b = a
   b%id = 12
   b%samples(1) = 40
   print *, a%id,b%base%id,a%samples,b%base%samples
   a%base = base(21,[5,6])
   print *, a%id,a%samples,a%extra
   b = child(base(31,[7,8]),41)
   print *, b
   b = child(id=51,samples=[9,10],extra=61)
   print *, b
   b = child(71,[11,12],81)
   print *, b
   records%id = [10,20]
   records(2)%base%id = 30
   print *, records%id,records%base%id
   last%id = 91
   last%base%samples(1) = 100
   last%child%base%id = 101
   print *, last%id,last%base%id,last%child%id,last%child%base%id
   print *, last%samples,last%child%base%samples,last%extra,last%tip
   last%child = a
   print *, last%id,last%base%samples,last%extra,last%tip
end program
