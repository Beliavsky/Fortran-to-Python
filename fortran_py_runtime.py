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
    "_f_allocate",
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
    "_f_minloc",
    "_f_maxloc",
    "_f_findloc",
    "_f_epsilon",
    "_f_norm2",
    "_f_sinpi",
    "_f_cospi",
    "_f_tanpi",
    "_f_fraction", "_f_exponent", "_f_scale", "_f_set_exponent",
    "_f_nearest", "_f_spacing", "_f_rrspacing", "_f_numeric_model",
    "_f_dim", "_f_sign",
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


def _f_allocate(model=None, shape=None, dtype=float, source=False, rank=1,
                factory=None, char_len=None):
    """Allocate typed storage; SOURCE copies values, MOLD supplies only shape."""
    if shape is None:
        if model is None:
            raise ValueError("allocation requires bounds or a model with known shape")
        shape = np.shape(model)
    shape = tuple(int(n) for n in shape)
    if len(shape) != rank:
        raise ValueError("allocation shape does not match declared rank")
    if source:
        if model is None:
            raise ValueError("SOURCE is unallocated or disassociated")
        model_shape = np.shape(model)
        if model_shape and model_shape != shape:
            raise ValueError("SOURCE array shape does not match allocation bounds")
        if factory is not None and not shape:
            import copy
            return copy.deepcopy(model)
        if char_len is not None:
            model = _f_str_assign(model, char_len)
        return _f_init_component_array(shape, model, dtype)
    # Do not read the model's values, even when it is uninitialized.
    if factory is not None:
        if not shape:
            return factory()
        return _f_init_component_array(shape, factory(), object)
    if char_len is not None:
        return np.full(shape, " " * max(0, int(char_len)), dtype=object)
    return np.empty(shape, dtype=dtype)


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


def _f_real_array(x):
    a = np.asarray(x)
    if a.dtype.kind != "f":
        raise TypeError("floating-point intrinsic requires REAL input")
    return a


def _f_fraction(x):
    return np.frexp(_f_real_array(x))[0]


def _f_exponent(x):
    return np.frexp(_f_real_array(x))[1]


def _f_scale(x, i):
    return np.ldexp(_f_real_array(x), np.asarray(i))


def _f_set_exponent(x, i):
    return np.ldexp(_f_fraction(x), np.asarray(i))


def _f_nearest(x, s):
    a = _f_real_array(x)
    direction = _f_real_array(s)
    if np.any(direction == 0):
        raise ValueError("NEAREST direction must be nonzero")
    toward = np.where(direction > 0, np.inf, -np.inf).astype(a.dtype)
    return np.nextafter(a, toward)


def _f_spacing(x):
    a = _f_real_array(x)
    info = np.finfo(a.dtype)
    # Fortran SPACING uses model numbers, not the subnormal lattice.
    distance = np.maximum(np.ldexp(np.ones_like(a), _f_exponent(a) - info.nmant - 1), info.tiny)
    return np.where(a == 0, info.tiny, distance)


def _f_rrspacing(x):
    a = _f_real_array(x)
    return np.ldexp(np.abs(_f_fraction(a)), np.finfo(a.dtype).nmant + 1)


def _f_numeric_model(x, inquiry):
    dtype = np.asarray(x).dtype
    if dtype.kind in "iu":
        info = np.iinfo(dtype)
        if inquiry == "huge":
            return info.max
        if inquiry == "digits":
            return info.bits - (dtype.kind == "i")
        if inquiry == "range":
            return int(math.floor(math.log10(info.max)))
        if inquiry == "radix":
            return 2
        raise TypeError(f"{inquiry.upper()} requires REAL or COMPLEX input")
    if dtype.kind not in "fc":
        raise TypeError("numeric model inquiry requires numeric input")
    info = np.finfo(dtype)
    if inquiry == "tiny":
        return info.tiny
    if inquiry == "huge":
        return info.max
    if inquiry == "digits":
        return info.nmant + 1
    if inquiry == "precision":
        return info.precision
    if inquiry == "range":
        return int(math.floor(min(math.log10(info.max), -math.log10(info.tiny))))
    if inquiry == "radix":
        return 2
    raise ValueError(f"unknown model inquiry: {inquiry}")


def _f_dim(x, y):
    return np.maximum(np.asarray(x) - np.asarray(y), 0)


def _f_sign(a, b):
    a, b = np.broadcast_arrays(np.asarray(a), np.asarray(b))
    if a.dtype.kind in "iu":
        return np.where(b < 0, -np.abs(a), np.abs(a))
    return np.copysign(np.abs(a), b)


def _f_epsilon(x):
    a = np.asarray(x)
    return np.finfo(a.dtype).eps


def _f_norm2(array, dim=None):
    a = np.asarray(array)
    if a.dtype.kind != "f":
        raise TypeError("NORM2 requires a real array")
    if dim is None and a.ndim != 1:
        raise ValueError("NORM2 without DIM requires a rank-one array")
    axis = 0 if dim is None else int(dim) - 1
    if not 0 <= axis < a.ndim:
        raise ValueError("NORM2 DIM is outside ARRAY rank")
    return np.hypot.reduce(np.abs(a), axis=axis, initial=0)


def _f_sinpi(x):
    r = np.fmod(np.asarray(x), 2.0)
    r = np.where(r > 1, r - 2, np.where(r < -1, r + 2, r))
    return np.where((r == 0) | (np.abs(r) == 1), np.copysign(0.0, r),
                    np.where(r == 0.5, 1.0, np.where(r == -0.5, -1.0, np.sin(np.pi * r))))


def _f_cospi(x):
    r = np.fmod(np.asarray(x), 2.0)
    r = np.where(r > 1, r - 2, np.where(r < -1, r + 2, r))
    return np.where(np.abs(r) == 0.5, 0.0,
                    np.where(r == 0, 1.0, np.where(np.abs(r) == 1, -1.0, np.cos(np.pi * r))))


def _f_tanpi(x):
    r = np.fmod(np.asarray(x), 1.0)
    r = np.where(r > 0.5, r - 1.0, np.where(r < -0.5, r + 1.0, r))
    return np.where(r == 0, np.copysign(0.0, r), np.tan(np.pi * r))


def _f_location(array, dim=None, mask=None, kind=None, back=False, *, mode, value=None):
    """Location in array-element order, independent of declared lower bounds."""
    a = np.asarray(array)
    if a.ndim == 0:
        raise ValueError("location intrinsic requires an array")
    dtype = np.dtype("int64" if kind is None else f"int{8 * int(kind)}")
    if dtype.kind != "i":
        raise ValueError("location KIND must specify an integer kind")
    if mask is None:
        eligible = np.ones(a.shape, dtype=bool)
    else:
        m = np.asarray(mask, dtype=bool)
        if m.ndim and m.shape != a.shape:
            raise ValueError("location MASK must conform to ARRAY")
        eligible = np.broadcast_to(m, a.shape)
    # Fortran CHARACTER comparisons blank-pad shorter operands.
    if a.dtype.kind in "US" or (a.dtype.kind == "O" and all(isinstance(x, str) for x in a.flat)):
        width = max([len(str(x)) for x in a.flat] + ([len(str(value))] if mode == "find" else [0]))
        a = np.asarray([str(x).ljust(width) for x in a.flat]).reshape(a.shape)
        if mode == "find":
            value = str(value).ljust(width)

    def locate(items, allowed):
        indices = np.flatnonzero(allowed)
        if not indices.size:
            return 0
        if mode == "find":
            hits = indices[items[indices] == value]
        else:
            selected = items[indices]
            if selected.dtype.kind in "US":
                target = min(selected.tolist()) if mode == "min" else max(selected.tolist())
            else:
                target = np.min(selected) if mode == "min" else np.max(selected)
            hits = indices[selected == target]
        return int(hits[-1] if back else hits[0]) + 1 if hits.size else 0

    if dim is None:
        position = locate(a.ravel(order="F"), eligible.ravel(order="F"))
        if not position:
            return np.zeros(a.ndim, dtype=dtype)
        return np.asarray(np.unravel_index(position - 1, a.shape, order="F"), dtype=dtype) + 1
    axis = int(dim) - 1
    if not 0 <= axis < a.ndim:
        raise ValueError("location DIM is outside ARRAY rank")
    moved, allowed = np.moveaxis(a, axis, -1), np.moveaxis(eligible, axis, -1)
    result = np.zeros(moved.shape[:-1], dtype=dtype)
    for index in np.ndindex(result.shape):
        result[index] = locate(moved[index], allowed[index])
    return result[()] if result.ndim == 0 else result


def _f_location_options(args, options):
    names = ("mask", "kind", "back") if args and np.asarray(args[0]).dtype.kind == "b" else ("dim", "mask", "kind", "back")
    if len(args) > len(names):
        raise TypeError("too many location intrinsic arguments")
    for name, value in zip(names, args):
        if name in options:
            raise TypeError(f"duplicate location argument: {name}")
        options[name] = value
    return options


def _f_minloc(array, *args, **options):
    return _f_location(array, mode="min", **_f_location_options(args, options))


def _f_maxloc(array, *args, **options):
    return _f_location(array, mode="max", **_f_location_options(args, options))


def _f_findloc(array, value, *args, **options):
    return _f_location(array, mode="find", value=value, **_f_location_options(args, options))


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
