program nested_sum_dimensions
   implicit none
   real(8) :: rets(2,3), mu(3), sig(3)
   integer :: a(2,3)
   rets(:,1) = [-0.1d0, 0.3d0]
   rets(:,2) = [0.02d0, 0.04d0]
   rets(:,3) = [0.01d0, -0.03d0]
   mu = sum(rets, dim=1) / real(size(rets,1), kind=8)
   sig = sqrt(sum((rets - spread(mu, dim=1, ncopies=size(rets,1)))**2, dim=1) &
              / real(size(rets,1), kind=8))
   print *, sig
   a = reshape([1,2,3,4,5,6], [2,3])
   print *, sqrt(real(sum(a, dim=1), kind=8))
   print *, sqrt(real(sum(a, dim=2), kind=8))
   print *, sum(sum(a, dim=1))
   print *, sum(sum(a, dim=2))
   print *, sum(sum(a, dim=1)**2)
   print *, sqrt(real(sum(a, dim=1, mask=a>2), kind=8))
end program nested_sum_dimensions
