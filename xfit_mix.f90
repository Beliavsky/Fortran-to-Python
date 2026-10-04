module python_mod
use, intrinsic :: iso_fortran_env, only: real64
implicit none
private
integer, parameter :: dp = real64

public :: isqrt_int       !@pyapi kind=function ret=integer args=x:integer:intent(in) desc="integer square root: return floor(sqrt(x)) for x >= 0"
public :: print_int_list  !@pyapi kind=subroutine args=a:integer(:):intent(in),n:integer:intent(in) desc="print integer list a(1:n) in python-style [..] format"
public :: random_normal_vec !@pyapi kind=subroutine args=x:real(dp)(:):intent(out) desc="fill x with N(0,1) variates using Box-Muller"
public :: random_choice2 !@pyapi kind=subroutine args=p:real(dp)(:):intent(in),n:integer:intent(in),z:integer(:):intent(out) desc="sample n labels in {0,1} with probabilities p(1:2)"
public :: random_choice_norep !@pyapi kind=subroutine args=npop:integer:intent(in),nsamp:integer:intent(in),z:integer(:):intent(out) desc="sample nsamp unique labels from 0..npop-1 without replacement"
public :: random_choice_prob !@pyapi kind=subroutine args=p:real(dp)(:):intent(in),n:integer:intent(in),z:integer(:):intent(out) desc="sample n labels in 0..size(p)-1 with probabilities p"
public :: sort_real_vec !@pyapi kind=subroutine args=x:real(dp)(:):intent(inout) desc="sort real vector x in ascending order"
public :: argsort_real !@pyapi kind=subroutine args=x:real(dp)(:):intent(in),idx:integer(:):intent(out) desc="argsort indices (0-based) of real vector"
public :: mean_1d !@pyapi kind=function ret=real(dp) args=x:real(dp)(:):intent(in) desc="mean of 1D real vector"
public :: var_1d !@pyapi kind=function ret=real(dp) args=x:real(dp)(:):intent(in),ddof:integer:intent(in):optional desc="variance of 1D real vector with optional ddof (numpy-style)"

contains

      pure integer function isqrt_int(x)
         ! integer square root: return floor(sqrt(x)) for x >= 0
         implicit none
         integer, intent(in) :: x  ! input integer (x >= 0 expected)
         integer :: r
         if (x <= 0) then
            isqrt_int = 0
            return
         end if
         r = int(sqrt(real(x, kind=dp)))
         do while ((r+1)*(r+1) <= x)
            r = r + 1
         end do
         do while (r*r > x)
            r = r - 1
         end do
         isqrt_int = r
      end function isqrt_int

      subroutine print_int_list(a, n)
         ! print integer list a(1:n) in python-style [..] format
         implicit none
         integer, intent(in) :: a(:)  ! array containing values to print
         integer, intent(in) :: n     ! number of elements from a to print
         integer :: j
         if (n <= 0) then
            write(*,'(a)') '[]'
            return
         end if
         write(*,'(a)', advance='no') '['
         do j = 1, n
            if (j > 1) write(*,'(a)', advance='no') ', '
            write(*,'(i0)', advance='no') a(j)
         end do
         write(*,'(a)') ']'
      end subroutine print_int_list

      subroutine random_normal_vec(x)
         ! fill x with N(0,1) variates using Box-Muller
         implicit none
         real(kind=dp), intent(out) :: x(:)
         integer :: i, n
         real(kind=dp) :: u1, u2, rad, theta
         real(kind=dp), parameter :: two_pi = 2.0_dp * acos(-1.0_dp)
         n = size(x)
         i = 1
         do while (i <= n)
            call random_number(u1)
            call random_number(u2)
            if (u1 <= tiny(1.0_dp)) cycle
            rad = sqrt(-2.0_dp * log(u1))
            theta = two_pi * u2
            x(i) = rad * cos(theta)
            if (i + 1 <= n) x(i + 1) = rad * sin(theta)
            i = i + 2
         end do
      end subroutine random_normal_vec

      subroutine random_choice2(p, n, z)
         ! sample n labels in {0,1} with probabilities p(1:2)
         implicit none
         real(kind=dp), intent(in) :: p(:)
         integer, intent(in) :: n
         integer, intent(out) :: z(:)
         integer :: i
         real(kind=dp) :: u, p1, s
         if (size(z) < n) stop "random_choice2: output array too small"
         if (size(p) < 2) stop "random_choice2: p must have at least 2 elements"
         p1 = max(0.0_dp, p(1))
         s = max(0.0_dp, p(1)) + max(0.0_dp, p(2))
         if (s > tiny(1.0_dp)) then
            p1 = p1 / s
         else
            p1 = 0.5_dp
         end if
         do i = 1, n
            call random_number(u)
            if (u < p1) then
               z(i) = 0
            else
               z(i) = 1
            end if
         end do
      end subroutine random_choice2

      subroutine random_choice_norep(npop, nsamp, z)
         integer, intent(in) :: npop, nsamp
         integer, intent(out) :: z(:)
         integer :: i, j, tmp
         real(kind=dp) :: u
         integer, allocatable :: pool(:)
         if (npop <= 0 .or. nsamp < 0) stop "random_choice_norep: invalid sizes"
         if (nsamp > npop) stop "random_choice_norep: nsamp > npop"
         if (size(z) < nsamp) stop "random_choice_norep: output array too small"
         allocate(pool(1:npop))
         do i = 1, npop
            pool(i) = i - 1
         end do
         do i = 1, nsamp
            call random_number(u)
            j = i + int(u * real(npop - i + 1, kind=dp))
            if (j < i) j = i
            if (j > npop) j = npop
            tmp = pool(i)
            pool(i) = pool(j)
            pool(j) = tmp
            z(i) = pool(i)
         end do
         if (allocated(pool)) deallocate(pool)
      end subroutine random_choice_norep

      subroutine random_choice_prob(p, n, z)
         real(kind=dp), intent(in) :: p(:)
         integer, intent(in) :: n
         integer, intent(out) :: z(:)
         integer :: i, j, k
         real(kind=dp) :: u, s
         real(kind=dp), allocatable :: cdf(:)
         k = size(p)
         if (k <= 0) stop "random_choice_prob: empty probability vector"
         if (size(z) < n) stop "random_choice_prob: output array too small"
         allocate(cdf(1:k))
         s = 0.0_dp
         do j = 1, k
            s = s + max(0.0_dp, p(j))
            cdf(j) = s
         end do
         if (s <= tiny(1.0_dp)) then
            do j = 1, k
               cdf(j) = real(j, kind=dp) / real(k, kind=dp)
            end do
         else
            cdf = cdf / s
         end if
         do i = 1, n
            call random_number(u)
            z(i) = k - 1
            do j = 1, k
               if (u <= cdf(j)) then
                  z(i) = j - 1
                  exit
               end if
            end do
         end do
         if (allocated(cdf)) deallocate(cdf)
      end subroutine random_choice_prob

      subroutine sort_real_vec(x)
         ! sort real vector x in ascending order
         implicit none
         real(kind=dp), intent(inout) :: x(:)
         integer :: i, j, n
         real(kind=dp) :: key
         n = size(x)
         do i = 2, n
            key = x(i)
            j = i - 1
            do while (j >= 1)
               if (x(j) <= key) exit
               x(j+1) = x(j)
               j = j - 1
            end do
            x(j+1) = key
         end do
      end subroutine sort_real_vec

      subroutine argsort_real(x, idx)
         real(kind=dp), intent(in) :: x(:)
         integer, intent(out) :: idx(:)
         integer :: i, j, n, key
         n = size(x)
         if (size(idx) < n) stop "argsort_real: output array too small"
         do i = 1, n
            idx(i) = i - 1
         end do
         do i = 2, n
            key = idx(i)
            j = i - 1
            do while (j >= 1)
               if (x(idx(j)+1) <= x(key+1)) exit
               idx(j+1) = idx(j)
               j = j - 1
            end do
            idx(j+1) = key
         end do
      end subroutine argsort_real

      pure real(kind=dp) function mean_1d(x)
         real(kind=dp), intent(in) :: x(:)
         if (size(x) <= 0) then
            mean_1d = 0.0_dp
         else
            mean_1d = sum(x) / real(size(x), kind=dp)
         end if
      end function mean_1d

      pure real(kind=dp) function var_1d(x, ddof)
         real(kind=dp), intent(in) :: x(:)
         integer, intent(in), optional :: ddof
         integer :: n, d
         real(kind=dp) :: mu
         n = size(x)
         if (present(ddof)) then
            d = ddof
         else
            d = 0
         end if
         if (n <= d .or. n <= 0) then
            var_1d = 0.0_dp
            return
         end if
         mu = mean_1d(x)
         var_1d = sum((x - mu)**2) / real(n - d, kind=dp)
      end function var_1d
end module python_mod

program xfit_mix_v4
   use python_mod, only: argsort_real, random_choice_norep, random_choice_prob, random_normal_vec, var_1d
   use, intrinsic :: ieee_arithmetic, only: ieee_value, ieee_quiet_nan
   use, intrinsic :: iso_fortran_env, only: real64
   implicit none
   integer, parameter :: dp = real64, nobs = 500
   type :: em_gmm_1d_dict_t
      real(kind=dp), allocatable :: weights(:)
      real(kind=dp), allocatable :: means(:)
      real(kind=dp), allocatable :: vars(:)
      real(kind=dp), allocatable :: loglik(:)
   end type em_gmm_1d_dict_t
   type(em_gmm_1d_dict_t) :: fit
   integer, allocatable :: idx_t(:)
   integer, allocatable :: z(:)
   real(kind=dp), allocatable :: mu_t(:)
   real(kind=dp), allocatable :: mu_true(:)
   real(kind=dp), allocatable :: sig_true(:)
   real(kind=dp), allocatable :: var_t(:)
   real(kind=dp), allocatable :: w_t(:)
   real(kind=dp), allocatable :: w_true(:)
   real(kind=dp), allocatable :: x(:)
   
   ! x: (n,), mu: (k,), var: (k,) -> (n,k)
   ! init parameters
   ! e-step (stable, in log space)
   ! (n,k)
   ! (1,k)
   ! (n,k)
   ! (n,1)
   ! (n,k)
   ! (n,k)
   ! m-step
   ! (k,)
   ! convergence check
   ! keep best run
   ! true mixture (3 components)
   print "('#obs: ', i0)", nobs
   if (allocated(w_true)) deallocate(w_true)
   allocate(w_true(1:3))
   w_true = [0.2_dp, 0.5_dp, 0.3_dp]
   if (allocated(mu_true)) deallocate(mu_true)
   allocate(mu_true(1:3))
   mu_true = [(-2.0_dp), 0.5_dp, 3.0_dp]
   if (allocated(sig_true)) deallocate(sig_true)
   allocate(sig_true(1:3))
   sig_true = [0.7_dp, 0.5_dp, 1.0_dp]
   call simulate_gmm_1d(nobs, w_true, mu_true, sig_true, 1, x, z)
   fit = em_gmm_1d(x, k=3, max_iter=300, tol=1e-07_dp, reg_covar=1e-06_dp, &
      seed=2, n_init=10)
   fit = sort_by_means(fit)
   ! sort true params by means for easy comparison
   if (allocated(idx_t)) deallocate(idx_t)
   allocate(idx_t(1:size(mu_true)))
   call argsort_real(mu_true, idx_t)
   w_t = w_true((idx_t + 1))
   mu_t = mu_true((idx_t + 1))
   var_t = (sig_true((idx_t + 1)) ** 2)
   print *, "true weights:", w_t
   print *, "est  weights:", fit%weights
   print *
   print *, "true means  :", mu_t
   print *, "est  means  :", fit%means
   print *
   print *, "true vars   :", var_t
   print *, "est  vars   :", fit%vars
   print *
   print *, "final loglik:", fit%loglik(size(fit%loglik))
   print *, "iters       :", size(fit%loglik)
   
   contains
   
   subroutine simulate_gmm_1d(n, weights, means, sigmas, seed, x, z)
      integer, intent(in) :: n
      real(kind=dp), intent(inout) :: weights(:)
      real(kind=dp), intent(inout) :: means(:)
      real(kind=dp), intent(inout) :: sigmas(:)
      integer, intent(in) :: seed
      real(kind=dp), allocatable, intent(out) :: x(:)
      integer, allocatable, intent(out) :: z(:)
      real(kind=dp) :: rng
      integer :: k
      
      block
         integer :: nseed_rng, i_rng
         integer, allocatable :: seed_rng(:)
         call random_seed(size=nseed_rng)
         allocate(seed_rng(1:nseed_rng))
         do i_rng = 1, nseed_rng
            seed_rng(i_rng) = int(seed) + 104729 * (i_rng - 1)
         end do
         call random_seed(put=seed_rng)
         if (allocated(seed_rng)) deallocate(seed_rng)
      end block
      rng = 0
      weights = (weights / sum(weights))
      k = size(weights)
      if (allocated(z)) deallocate(z)
      allocate(z(1:n))
      call random_choice_prob(weights, n, z)
      if (allocated(x)) deallocate(x)
      allocate(x(1:n))
      call random_normal_vec(x)
      block
         integer :: i_norm
         do i_norm = 1, n
            x(i_norm) = means(z(i_norm) + 1) + sigmas(z(i_norm) + 1) * x(i_norm)
         end do
      end block
      x = x
      z = z
   end subroutine simulate_gmm_1d
   
   function logsumexp(a, axis, keepdims) result(logsumexp_result)
      real(kind=dp), intent(in) :: a(:,:)
      integer, intent(in) :: axis
      logical, intent(in) :: keepdims
      real(kind=dp), allocatable :: logsumexp_result(:,:)
      integer :: i, j
      real(kind=dp) :: m, s
      if (axis == 1) then
         allocate(logsumexp_result(1:size(a,1),1:1))
         do i = 1, size(a,1)
            m = maxval(a(i,:))
            s = 0.0_dp
            do j = 1, size(a,2)
               s = s + exp(a(i,j) - m)
            end do
            logsumexp_result(i,1) = m + log(s)
         end do
      else if (axis == 0) then
         allocate(logsumexp_result(1:1,1:size(a,2)))
         do j = 1, size(a,2)
            m = maxval(a(:,j))
            s = 0.0_dp
            do i = 1, size(a,1)
               s = s + exp(a(i,j) - m)
            end do
            logsumexp_result(1,j) = m + log(s)
         end do
      else
         stop "logsumexp: unsupported axis"
      end if
      if (.not. keepdims) then
         ! keep 2D result shape in this subset
      end if
   end function logsumexp
   
   function normal_logpdf_1d(x, mu, var) result(normal_logpdf_1d_result)
      real(kind=dp), intent(in) :: x(:)
      real(kind=dp), intent(in) :: mu(:)
      real(kind=dp), intent(in) :: var(:)
      real(kind=dp), allocatable :: normal_logpdf_1d_result(:,:)
      integer :: i, j
      real(kind=dp) :: log2pi
      log2pi = log(2.0_dp * acos(-1.0_dp))
      allocate(normal_logpdf_1d_result(1:size(x),1:size(mu)))
      do i = 1, size(x)
         do j = 1, size(mu)
            normal_logpdf_1d_result(i,j) = -0.5_dp * (log2pi + log(var(j)) + (x(i) - mu(j))**2 / var(j))
         end do
      end do
   end function normal_logpdf_1d
   
   function em_gmm_1d(x, k, max_iter, tol, reg_covar, seed, n_init) result(em_gmm_1d_result)
      real(kind=dp), intent(inout) :: x(:)
      integer, intent(in) :: k
      integer, intent(in) :: max_iter
      real(kind=dp), intent(in) :: tol
      real(kind=dp), intent(in) :: reg_covar
      integer, intent(in) :: seed
      integer, intent(in) :: n_init
      type(em_gmm_1d_dict_t) :: em_gmm_1d_result
      real(kind=dp) :: ll, prev_ll, rng, var0
      integer :: init, it, n, n_ll_hist
      type(em_gmm_1d_dict_t) :: best
      real(kind=dp), allocatable :: ll_hist(:)
      real(kind=dp), allocatable :: log_joint(:,:)
      real(kind=dp), allocatable :: log_norm(:,:)
      real(kind=dp), allocatable :: log_pdf(:,:)
      real(kind=dp), allocatable :: log_resp(:,:)
      real(kind=dp), allocatable :: log_w(:,:)
      real(kind=dp), allocatable :: mu(:)
      real(kind=dp), allocatable :: nk(:)
      real(kind=dp), allocatable :: resp(:,:)
      real(kind=dp), allocatable :: var(:)
      real(kind=dp), allocatable :: w(:)
      
      ! x: (n,), mu: (k,), var: (k,) -> (n,k)
      n = size(x)
      block
         integer :: nseed_rng, i_rng
         integer, allocatable :: seed_rng(:)
         call random_seed(size=nseed_rng)
         allocate(seed_rng(1:nseed_rng))
         do i_rng = 1, nseed_rng
            seed_rng(i_rng) = int(seed) + 104729 * (i_rng - 1)
         end do
         call random_seed(put=seed_rng)
         if (allocated(seed_rng)) deallocate(seed_rng)
      end block
      rng = 0
      do init = 0, (n_init - 1)
         ! init parameters
         if (allocated(mu)) deallocate(mu)
         allocate(mu(1:k))
         block
            integer :: i_ch
            integer, allocatable :: idx_ch(:)
            allocate(idx_ch(1:k))
            call random_choice_norep(n, k, idx_ch)
            do i_ch = 1, k
               mu(i_ch) = x(idx_ch(i_ch) + 1)
            end do
            if (allocated(idx_ch)) deallocate(idx_ch)
         end block
         var0 = (var_1d(x) + reg_covar)
         if (allocated(var)) deallocate(var)
         allocate(var(1:k))
         var = var0
         if (allocated(w)) deallocate(w)
         allocate(w(1:k))
         w = (1.0_dp / k)
         if (.not. allocated(ll_hist)) allocate(ll_hist(1:n))
         n_ll_hist = 0
         ll_hist = 0
         prev_ll = (-huge(1.0_dp))
         do it = 0, (max_iter - 1)
            ! e-step (stable, in log space)
            ! (n,k)
            log_pdf = normal_logpdf_1d(x, mu, var)
            ! (1,k)
            log_w = reshape(log((w + 1e-300_dp)), [1, size(log((w + 1e-300_dp)))])
            ! (n,k)
            log_joint = (spread(reshape(log_w, [size(log_w,2)]), dim=1, ncopies=size(log_pdf,1)) + log_pdf)
            ! (n,1)
            log_norm = logsumexp(log_joint, 1, .true.)
            ! (n,k)
            log_resp = (log_joint - spread(reshape(log_norm, [size(log_norm,1)]), dim=2, ncopies=size(log_joint,2)))
            ! (n,k)
            resp = exp(log_resp)
            ll = real(sum(log_norm), kind=dp)
            n_ll_hist = n_ll_hist + 1
            ll_hist(n_ll_hist) = ll
            ! m-step
            ! (k,)
            nk = (sum(resp, dim=(0 + 1)) + 1e-300_dp)
            w = (nk / n)
            mu = (sum((resp * spread(x, dim=2, ncopies=size(resp,2))), dim=(0 + 1)) / nk)
            var = (sum((resp * ((spread(x, dim=2, ncopies=size(reshape(mu, [1, size(mu)]),2)) - spread(mu, dim=1, ncopies=size(reshape(x, [size(x), 1]),1))) ** 2)), dim=(0 + 1)) / nk)
            var = max(var, reg_covar)
            ! convergence check
            if (((ll - prev_ll) < tol)) then
               exit
            end if
            prev_ll = ll
         end do
         ! keep best run
         if ((.not. allocated(best%loglik))) then
            best%weights = w
            best%means = mu
            best%vars = var
            best%loglik = ll_hist(1:n_ll_hist)
         else
            if ((ll_hist(n_ll_hist) > best%loglik(size(best%loglik)))) then
               best%weights = w
               best%means = mu
               best%vars = var
               best%loglik = ll_hist(1:n_ll_hist)
            end if
         end if
      end do
      em_gmm_1d_result%weights = best%weights
      em_gmm_1d_result%means = best%means
      em_gmm_1d_result%vars = best%vars
      em_gmm_1d_result%loglik = best%loglik
   end function em_gmm_1d
   
   function sort_by_means(params) result(sort_by_means_result)
      type(em_gmm_1d_dict_t), intent(in) :: params
      type(em_gmm_1d_dict_t) :: sort_by_means_result
      type(em_gmm_1d_dict_t) :: out
      integer, allocatable :: idx(:)
      
      ! x: (n,), mu: (k,), var: (k,) -> (n,k)
      ! init parameters
      ! e-step (stable, in log space)
      ! (n,k)
      ! (1,k)
      ! (n,k)
      ! (n,1)
      ! (n,k)
      ! (n,k)
      ! m-step
      ! (k,)
      ! convergence check
      ! keep best run
      if (allocated(idx)) deallocate(idx)
      allocate(idx(1:size(params%means)))
      call argsort_real(params%means, idx)
      out%weights = params%weights((idx + 1))
      out%means = params%means((idx + 1))
      out%vars = params%vars((idx + 1))
      out%loglik = params%loglik
      sort_by_means_result%weights = out%weights
      sort_by_means_result%means = out%means
      sort_by_means_result%vars = out%vars
      sort_by_means_result%loglik = out%loglik
   end function sort_by_means
   
end program xfit_mix_v4
