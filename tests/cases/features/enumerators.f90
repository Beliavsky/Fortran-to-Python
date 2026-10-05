module palette
   implicit none
   private
   integer, parameter :: base = 4
   enum, bind(c)
      enumerator :: red = base, green, &
         blue = green + 2
      enumerator :: hidden = -7, following
   end enum
   public :: green, code_sum
contains
   integer function code_sum()
      code_sum = red + blue + hidden + following
   end function
end module

program enumerators
   use palette, only: green, code_sum
   use iso_c_binding, only: c_int
   implicit none
   integer(c_int) :: color
   integer :: values(green)
   enum, bind(c)
      enumerator :: zero, one, negative = -3, after_negative
      enumerator :: seven = one + 6, eight, duplicate_value = seven
   end enum
   enum, bind(c)
      enumerator :: reset_zero, reset_one
   end enum
   color = green
   values = eight
   print *, zero, one, negative, after_negative, seven, eight, duplicate_value
   print *, reset_zero, reset_one, green, code_sum(), sum(values)
   select case (color)
   case (green)
      print *, 'green'
   case default
      print *, 'unexpected'
   end select
   print *, local_code()
   block
      enum, bind(c)
         enumerator :: green = 200, next_green
      end enum
      print *, green, next_green
   end block
   print *, green
contains
   integer function local_code()
      enum, bind(c)
         enumerator :: green = 100, next_green
      end enum
      local_code = next_green
   end function
end program
