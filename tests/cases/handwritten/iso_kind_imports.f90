module kind_module
   use iso_fortran_env, only: module_kind => int16
   implicit none
contains
   integer function from_module()
      from_module = module_kind
   end function from_module
end module kind_module
program iso_kind_imports
   use iso_fortran_env, only: tiny_kind => int8, short_kind => int16, long_kind => int64
   use kind_module, only: from_module
   implicit none
   integer(kind=long_kind) :: values(2)
   values = [100,200]
   print *, tiny_kind, short_kind, long_kind, from_module()
   print *, sum(values), local_kind()
contains
   integer function local_kind()
      use :: iso_fortran_env, only: local_alias => int32
      local_kind = local_alias
   end function local_kind
end program iso_kind_imports
