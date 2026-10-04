"""Shared runtime helpers for Python emitted from scientific transpilers.

Used by xf2p.py and xr2p.py outputs.
"""
from __future__ import annotations

import math
import numpy as np

_np_reshape_orig = np.reshape


def _reshape_with_pad(a, newshape, order="C", pad=None):
    """NumPy reshape wrapper with optional Fortran-style pad support."""
    if pad is None and not isinstance(order, (str, bytes)):
        pad = order
        order = "F"
    shp = tuple(int(v) for v in np.asarray(newshape).ravel())
    if pad is None:
        return _np_reshape_orig(a, shp, order=order)
    arr = np.asarray(a)
    target = int(np.prod(np.asarray(shp, dtype=np.int64)))
    src = np.asarray(pad if np.asarray(pad).size > 0 else arr)
    if src.size == 0:
        src = np.zeros(target, dtype=arr.dtype if arr.size else np.float64)
    arr2 = np.resize(src, target)
    return _np_reshape_orig(arr2, shp, order="F")


np.reshape = _reshape_with_pad

__all__ = [
    "_reshape_with_pad",
    "_f_size",
    "_f_spread",
    "_f_assign_array",
    "_f_init_component_array",
    "_f_section_slice",
    "_f_dot_product",
    "_f_reshape",
    "_f_str_assign",
    "_f_len_trim",
    "_f_adjustl",
    "_f_index",
    "merge",
    "pack",
    "count",
    "maxval",
    "minval",
    "spread",
    "huge",
    "tiny",
    "floor",
    "nint",
    "ieee_value",
    "mean_1d",
    "var_1d",
    "argsort_real",
    "random_normal_vec",
    "random_choice2",
    "random_choice_prob",
    "random_choice_norep",
    "r_matmul",
    "matmul",
]


def _f_str_assign(value, length):
    """Fixed-length CHARACTER assignment: truncate or pad with blank spaces."""
    length = max(0, int(length))
    array = np.asarray(value, dtype=object)
    def convert(text):
        return str(text)[:length].ljust(length)
    if array.ndim == 0:
        return convert(array.item())
    return np.vectorize(convert, otypes=[object])(array)


def _f_len_trim(value):
    """Elemental LEN_TRIM removes Fortran blanks, not tabs/newlines."""
    array = np.asarray(value, dtype=object)
    if array.ndim == 0:
        return len(str(array.item()).rstrip(" "))
    return np.vectorize(lambda text: len(str(text).rstrip(" ")), otypes=[int])(array)


def _f_adjustl(value):
    """Elemental ADJUSTL moves leading blanks to the end without changing LEN."""
    def adjust(text):
        text = str(text)
        return text.lstrip(" ").ljust(len(text))
    array = np.asarray(value, dtype=object)
    if array.ndim == 0:
        return adjust(array.item())
    return np.vectorize(adjust, otypes=[object])(array)


def _f_index(string, substring, back=False):
    """Elemental Fortran INDEX: one-based positions, zero when not found."""
    def find(text, needle, reverse):
        text, needle = str(text), str(needle)
        return (text.rfind(needle) if reverse else text.find(needle)) + 1
    a, b, reverse = np.broadcast_arrays(np.asarray(string, dtype=object),
                                        np.asarray(substring, dtype=object), np.asarray(back, dtype=bool))
    if a.ndim == 0:
        return find(a.item(), b.item(), reverse.item())
    return np.vectorize(find, otypes=[int])(a,b,reverse)


def _f_section_slice(a, dim, lower_bound, lower=None, upper=None, stride=1):
    """Inclusive Fortran triplet -> Python slice, including reverse sections."""
    stride = int(stride)
    if stride == 0:
        raise ValueError("Fortran array section stride must not be zero")
    base = int(lower_bound)
    size = np.asarray(a).shape[int(dim)]
    last_bound = base + size - 1
    # Unlike Python, Fortran's omitted bounds do not change with stride sign.
    first = base if lower is None else int(lower)
    last = last_bound if upper is None else int(upper)
    count = max(0, (last - first) // stride + 1)
    if count == 0:
        return slice(0, 0, stride)
    final = first + (count - 1) * stride
    if not (base <= first <= last_bound and base <= final <= last_bound):
        raise IndexError("Fortran array section is out of bounds")
    stop = last - base + (1 if stride > 0 else -1)
    # A literal -1 stop indexes from the end in Python, rather than denoting
    # the exclusive position before the first element.
    if stride < 0 and stop < 0:
        stop = None
    return slice(first - base, stop, stride)


def _f_size(a, dim=None):
    """Fortran-like size with optional 1-based dimension argument."""
    if hasattr(a, "__dict__"):
        if dim is None:
            return len(a.__dict__)
        return len(a.__dict__)
    if isinstance(a, dict):
        if not a:
            return 0
        if dim is None:
            first = next(iter(a.values()))
            return int(np.asarray(first).size)
        k = int(dim)
        if k == 1:
            first = next(iter(a.values()))
            return int(np.asarray(first).size)
        if k == 2:
            return int(len(a))
        return 0
    arr = np.asarray(a)
    if dim is None:
        return arr.size
    k = int(dim) - 1
    if k < 0 or k >= arr.ndim:
        return 0
    return arr.shape[k]


def _f_spread(a, dim=None, ncopies=None):
    """Fortran-like spread: replicate array along a 1-based dimension."""
    arr = np.asarray(a)
    d = 1 if dim is None else int(dim)
    ncopy = 1 if ncopies is None else int(ncopies)
    axis = d - 1
    ex = np.expand_dims(arr, axis=axis)
    return np.repeat(ex, ncopy, axis=axis)


def _f_init_component_array(shape, initializer, dtype):
    """Initialize fresh component storage, with independent derived elements."""
    result = np.full(shape, initializer, dtype=dtype)
    if result.dtype == object:
        import copy
        for index in np.ndindex(result.shape):
            # Copy separately: deepcopy of the whole array would retain aliases
            # introduced by scalar expansion of a derived-type initializer.
            result[index] = copy.deepcopy(result[index])
    return result


def _f_assign_array(lhs, rhs):
    """Assign with array-shape-aware replacement semantics used by transpiled code."""
    try:
        arr = np.array(rhs, copy=True)
    except Exception:
        if isinstance(rhs, (list, tuple)):
            parts = [np.asarray(v).ravel(order="F") for v in rhs]
            arr = np.concatenate(parts) if parts else np.asarray([], dtype=np.float64)
        else:
            raise
    if lhs is None:
        return arr
    lhs_arr = np.asarray(lhs)
    if arr.ndim == 0 and lhs_arr.ndim > 0:
        lhs_arr[...] = arr.item()
        return lhs
    if lhs_arr.shape != arr.shape or lhs_arr.dtype != arr.dtype:
        return arr
    lhs_arr[...] = arr
    return lhs


def merge(tsource, fsource, mask):
    """Fortran MERGE equivalent for scalar/array masks."""
    m = np.asarray(mask)
    if m.ndim == 0:
        return tsource if bool(m) else fsource
    return np.where(m, tsource, fsource)


def pack(x, mask):
    """Fortran PACK equivalent."""
    a = np.asarray(x)
    m = np.asarray(mask, dtype=bool)
    return a[m]


def count(x):
    """Count non-zero/true entries."""
    return int(np.count_nonzero(np.asarray(x)))


def maxval(x, dim=None):
    """Fortran MAXVAL equivalent with 1-based dim."""
    a = np.asarray(x)
    if dim is None:
        return np.max(a)
    return np.max(a, axis=int(dim) - 1)


def minval(x, dim=None):
    """Fortran MINVAL equivalent with 1-based dim."""
    a = np.asarray(x)
    if dim is None:
        return np.min(a)
    return np.min(a, axis=int(dim) - 1)


def spread(a, dim=1, ncopies=1):
    """Alias for spread used by some generated code."""
    return _f_spread(a, dim=dim, ncopies=ncopies)


def huge(x):
    """Return a large representable value for x's dtype."""
    a = np.asarray(x)
    if a.dtype.kind in "iu":
        return np.iinfo(a.dtype).max
    return np.finfo(np.float64).max


def tiny(x):
    """Return tiny positive float."""
    return np.finfo(np.float64).tiny


def floor(x):
    """Floor helper for scalar/array values."""
    a = np.asarray(x)
    if a.ndim == 0:
        return math.floor(float(a))
    return np.floor(a)


def nint(x):
    """Nearest integer (Fortran NINT-like)."""
    return int(np.rint(float(np.asarray(x))))


def ieee_value(x, what):
    """Return IEEE quiet NaN placeholder."""
    del x, what
    return np.nan


def ieee_is_finite(x):
    """IEEE finite-value predicate."""
    return np.isfinite(np.asarray(x, dtype=np.float64))


def mean_1d(x):
    """Mean of 1D input with empty fallback 0.0."""
    a = np.asarray(x, dtype=np.float64)
    return np.float64(np.mean(a)) if a.size else np.float64(0.0)


def var_1d(x):
    """Sample variance of 1D input with safe fallback."""
    a = np.asarray(x, dtype=np.float64)
    return np.float64(np.var(a, ddof=1)) if a.size > 1 else np.float64(0.0)


def argsort_real(x):
    """Argsort for real-valued input."""
    return np.argsort(np.asarray(x, dtype=np.float64))


def random_normal_vec(x):
    """Fill vector with standard normal draws."""
    return _f_assign_array(x, np.random.normal(size=np.asarray(x).shape))


def random_choice2(weights, n, z=None):
    """Sample component labels 0..k-1 by probability weights."""
    p = np.asarray(weights, dtype=np.float64)
    p = p / np.sum(p)
    out = np.random.choice(np.arange(p.size), size=int(n), p=p)
    return _f_assign_array(z, out)


def random_choice_prob(weights, n, z=None):
    """Alias for random_choice2."""
    return random_choice2(weights, n, z)


def random_choice_norep(n, k, out=None):
    """Sample without replacement from 0..n-1."""
    vals = np.random.choice(np.arange(int(n)), size=int(k), replace=False)
    return _f_assign_array(out, vals)


def r_matmul(a, b):
    """Matrix multiply wrapper."""
    return np.matmul(np.asarray(a), np.asarray(b))


def matmul(a, b):
    """Fortran MATMUL, including logical AND/OR matrix multiplication."""
    aa, bb = np.asarray(a), np.asarray(b)
    if aa.dtype.kind == bb.dtype.kind == "b":
        return np.matmul(aa.astype(np.int64), bb.astype(np.int64)) != 0
    return r_matmul(a, b)


def _f_dot_product(a, b):
    """Fortran DOT_PRODUCT conjugates the first complex vector."""
    aa, bb = np.asarray(a), np.asarray(b)
    if aa.ndim != 1 or bb.ndim != 1 or aa.shape != bb.shape:
        raise ValueError("DOT_PRODUCT requires equal-length rank-one vectors")
    if aa.dtype.kind == bb.dtype.kind == "b":
        return np.any(aa & bb)
    return np.vdot(aa, bb)


def _f_reshape(source, shape, pad=None, order=None):
    """Fortran RESHAPE with column-major elements and optional PAD/ORDER."""
    dimensions = tuple(int(n) for n in np.asarray(shape).ravel())
    if not dimensions or any(n < 0 for n in dimensions):
        raise ValueError("RESHAPE requires a nonempty nonnegative shape")
    count = math.prod(dimensions)
    values = np.asarray(source).ravel(order="F")
    if count > values.size:
        padding = np.asarray(pad).ravel(order="F") if pad is not None else np.array([])
        if padding.size == 0:
            raise ValueError("RESHAPE source is too short without nonempty PAD")
        values = np.concatenate((values, np.resize(padding, count - values.size)))
    permutation = list(range(len(dimensions))) if order is None else [int(n)-1 for n in np.asarray(order).ravel()]
    if sorted(permutation) != list(range(len(dimensions))):
        raise ValueError("RESHAPE ORDER must be a permutation of dimension indices")
    permuted_shape = tuple(dimensions[i] for i in permutation)
    result = _np_reshape_orig(values[:count], permuted_shape, order="F")
    return np.transpose(result, axes=np.argsort(permutation))
