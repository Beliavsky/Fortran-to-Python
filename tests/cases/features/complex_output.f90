program complex_output
   use iso_fortran_env, only: real32, real64
   implicit none
   complex(real64) :: z, matrix(2,2)
   complex(real32) :: single
   z = (1.0_real64, 2.0_real64)
   print *, 'scalar', z, conjg(z), exp(z), log(z), sin(z), sqrt(z)
   single = (1.25_real32, -2.5_real32)
   print *, 'single', single
   matrix(1,1) = (1.2345678901234567_real64, -2.345678901234567_real64)
   matrix(2,1) = (1e-200_real64, -1e-200_real64)
   matrix(1,2) = (1e200_real64, -1e200_real64)
   matrix(2,2) = (-0.0_real64, 0.0_real64)
   print *, 'matrix', matrix
end program
