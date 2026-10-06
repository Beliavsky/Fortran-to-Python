"""Shared runtime helpers for Python emitted from scientific transpilers.

Used by xf2p.py and xr2p.py outputs.
"""
from __future__ import annotations

import math
import re
import sys
import functools
import inspect
import os
import tempfile
import subprocess
import weakref
import numpy as np

_np_reshape_orig = np.reshape

# Unit numbers remain integers, including negative NEWUNIT values. Connections
# are shared by procedures in the same Python process, just as in Fortran.
_f_file_units = {}


def _f_file(unit, action=None):
    if hasattr(unit, "read") or hasattr(unit, "write"):
        return unit  # Compatibility with older generated programs.
    number = int(unit)
    if number in _f_file_units:
        permitted = _f_file_units[number][3]
        if action is not None and permitted not in {action, "readwrite"}:
            raise OSError(f"Cannot {action.upper()} unit opened with ACTION='{permitted}'")
        return _f_file_units[number][0]
    if number in (5, 6, 0):
        return {5: sys.stdin, 6: sys.stdout, 0: sys.stderr}[number]
    raise OSError(f"Fortran unit {number} is not connected")


def _f_file_open(unit=None, *, file=None, status="unknown", action="readwrite",
                 position="asis", access="sequential", form="formatted"):
    status, action, position, access, form = (
        str(value).strip().lower() for value in (status, action, position, access, form))
    if access != "sequential" or form != "formatted":
        raise ValueError("Only sequential formatted file I/O is supported")
    if status not in {"old", "new", "replace", "unknown", "scratch"}:
        raise ValueError(f"Unsupported OPEN status: {status}")
    if action not in {"read", "write", "readwrite"} or position not in {"asis", "rewind", "append"}:
        raise ValueError("Unsupported OPEN action or position")
    if status == "scratch" and file is not None:
        raise ValueError("Scratch files cannot have a FILE name")
    if status != "scratch" and file is None:
        raise ValueError("OPEN requires FILE unless STATUS is scratch")
    if unit is None:
        number = -10
        while number in _f_file_units:
            number -= 1
    else:
        number = int(unit)
        if number < 0:
            raise ValueError("Explicit UNIT must be nonnegative; use NEWUNIT for negative units")
    if number in _f_file_units:
        raise ValueError("Reopening a connected unit requires CLOSE first")
    filename = None if file is None else str(file).rstrip()
    if status == "scratch":
        handle = tempfile.TemporaryFile(mode="w+", encoding="utf-8", newline="")
    else:
        mode = {"old": "r+", "new": "x+", "replace": "w+", "unknown": "r+"}[status]
        if status == "unknown" and not os.path.exists(filename):
            mode = "w+"
        if action == "read" and status in {"old", "unknown"} and os.path.exists(filename):
            mode = "r"
        handle = open(filename, mode, encoding="utf-8", newline="")
    if position == "append":
        handle.seek(0, 2)
    _f_file_units[number] = (handle, filename, status == "scratch", action)
    return number


def _f_file_close(unit, status=None):
    number = int(unit)
    if status is not None and str(status).strip().lower() not in {"keep", "delete"}:
        raise ValueError("Unsupported CLOSE status")
    if number not in _f_file_units:
        return  # Closing an unconnected unit is permitted by Fortran.
    handle, filename, scratch, _action = _f_file_units[number]
    disposition = str(status).strip().lower() if status is not None else ("delete" if scratch else "keep")
    if scratch and disposition == "keep":
        raise ValueError("Scratch files cannot be kept")
    handle.close()
    del _f_file_units[number]
    if disposition == "delete" and filename is not None:
        os.remove(filename)


def _f_file_rewind(unit):
    handle = _f_file(unit)
    handle.flush()
    handle.seek(0)


def _f_file_read(unit, counts, kinds):
    """Read complete numeric/logical input lists, continuing across records."""
    if int(unit) in _f_file_units and _f_file_units[int(unit)][3] == "write":
        raise OSError("Cannot READ a unit opened with ACTION='write'")
    handle = _f_file(unit)
    needed = sum(int(n) for n in counts)
    tokens = []
    consumed_record = False
    while len(tokens) < needed or not consumed_record:
        line = handle.readline()
        if line == "":
            raise EOFError("End of file")
        consumed_record = True
        # Null values, repeats, slash termination, and complex/character lists
        # require additional Fortran parsing; do not silently misread them.
        if re.search(r",\s*,|^\s*,|[,\s]$", line.rstrip()) and "," in line:
            raise ValueError("Null list-directed input values are not supported")
        tokens.extend(line.replace(",", " ").split())
    result, offset = [], 0
    for count, kind in zip(counts, kinds):
        values = []
        for token in tokens[offset:offset + int(count)]:
            if kind == "integer":
                value = int(token)
            elif kind == "logical":
                spelling = token.strip(".").lower()
                if spelling not in {"t", "true", "f", "false"}:
                    raise ValueError(f"Invalid logical input: {token}")
                value = spelling in {"t", "true"}
            elif kind == "real":
                value = float(token.replace("D", "e").replace("d", "e"))
            else:
                raise ValueError(f"Unsupported list-directed input type: {kind}")
            values.append(value)
        result.append(values)
        offset += int(count)
    return result


def _f_internal_read_parts(text, character_targets=None):
    """Tokenize basic internal list-directed input without dropping null fields.

    Commas and whitespace separate values. Quoted character values preserve
    embedded commas/spaces and doubled quotes. Repeats, null values and slash
    termination require additional assignment semantics and are rejected.
    """
    if not isinstance(text, str):
        raise ValueError('Internal READ requires a scalar character record')
    result, position, comma_allowed = [], 0, False
    while position < len(text):
        if character_targets is not None and len(result) == len(character_targets):
            break  # The remainder of the record is not part of this READ.
        if text[position].isspace():
            position += 1
            continue
        if text[position] == ',':
            if not comma_allowed:
                raise ValueError('Null list-directed input values are not supported')
            comma_allowed = False
            position += 1
            continue
        if text[position] in "'\"":
            if character_targets is not None and not character_targets[len(result)]:
                raise ValueError('Quoted list-directed input requires a character target')
            quote = text[position]
            position += 1
            value = []
            while position < len(text):
                char = text[position]
                position += 1
                if char == quote:
                    if position < len(text) and text[position] == quote:
                        value.append(quote)
                        position += 1
                        continue
                    break
                value.append(char)
            else:
                raise ValueError('Unterminated quoted list-directed input value')
            if position < len(text) and not (text[position].isspace() or text[position] == ','):
                raise ValueError('Missing separator after quoted list-directed input value')
            token = ''.join(value)
        else:
            start = position
            while position < len(text) and not (text[position].isspace() or text[position] == ','):
                position += 1
            token = text[start:position]
            if '/' in token or '*' in token:
                raise ValueError('List-directed repeats and slash termination are not supported')
        result.append(token)
        comma_allowed = True
    return result


def _f_internal_read(text, descriptors, lengths):
    """Read scalar fixed-width fields from one padded internal record.

    Descriptors are validated by the translator. Reversion, record changes,
    scale/blank controls and whole-array targets are intentionally unsupported.
    """
    if not isinstance(text, str):
        raise ValueError('Internal READ requires a scalar character record')
    result, position = [], 0
    for code, width, decimals in descriptors:
        if len(result) == len(lengths):
            break
        if code == 'x':
            position += width
            continue
        length = lengths[len(result)]
        width = length if width is None else width
        field = text[position:position + width].ljust(width)
        position += width
        token = field.replace(' ', '')  # Default BN: embedded blanks are ignored.
        if code == 'a':
            value = _f_str_assign(field[-length:] if length else '', length)
        elif code == 'i':
            if token and not re.fullmatch(r'[+-]?\d+', token):
                raise ValueError(f'Invalid integer input field: {field!r}')
            value = int(token or '0')
        elif code == 'l':
            match = re.match(r'\.?([tf])', token, re.I)
            if not match:
                raise ValueError(f'Invalid logical input field: {field!r}')
            value = match.group(1).lower() == 't'
        else:
            token = token.replace('D', 'e').replace('d', 'e')
            # Fortran also permits an exponent sign without E/D.
            token = re.sub(r'(?<=[\d.])([+-]\d+)$', r'e\1', token)
            value = float(token or '0')
            if '.' not in token and token:
                value *= 10.0 ** -decimals
        result.append(value)
    return result


def _f_file_read_assign(target, values):
    array = np.asarray(target)
    result = np.asarray(values, dtype=array.dtype).reshape(array.shape, order="F")
    if array.ndim:
        array[...] = result
        return target
    return result.item()


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

def _f_array_indices(array, *indices):
    """Cartesian Fortran subscripts, with basic sections kept as views.

    Inputs are zero-based. Return indices, not a copy of the selection,
    so the same helper supports reads and assignment into the original.
    """
    if not any(not isinstance(i, slice) and np.ndim(i) > 0 for i in indices):
        return tuple(indices)
    if len(indices) != np.ndim(array):
        raise ValueError("Fortran subscript count must match array rank")
    selectors, retained = [], []
    for axis, index in enumerate(indices):
        if isinstance(index, slice):
            index = np.arange(array.shape[axis])[index]
        else:
            index = np.asarray(index)
            if index.ndim > 1 or index.dtype.kind not in "iu":
                raise TypeError("Fortran subscripts must be scalar or rank-1 integers")
            if np.any(index < 0) or np.any(index >= array.shape[axis]):
                raise IndexError("Fortran array subscript out of bounds")
        selectors.append(index)
        if np.ndim(index) == 1:
            retained.append(axis)
    for axis, index in zip(retained, np.ix_(*(selectors[a] for a in retained))):
        selectors[axis] = index
    return tuple(selectors)


__all__ = [
    "_f_file", "_f_file_open", "_f_file_close", "_f_file_rewind",
    "_f_file_read", "_f_file_read_assign", "_f_internal_read", "_f_internal_read_parts",
    "_f_array_indices",
    "_f_elemental_subroutine",
    "_f_component_array", "_f_assign_component_array",
    "_f_extended_type",
    "_f_product", "_f_unpack", "_f_cshift", "_f_eoshift", "_f_is_contiguous",
    "_f_associated", "_f_pointer_target", "_f_pointer_associate",
    "_f_contiguous_arguments", "_f_adjustr", "_f_scan", "_f_verify", "_f_repeat",
    "_f_command_argument_count", "_f_get_command_argument", "_f_bits",
    "_f_execute_command_line",
    "_reshape_with_pad",
    "_f_size",
    "_f_shape",
    "_f_rank",
    "_f_spread",
    "_f_assign_array",
    "_f_init_component_array",
    "_f_allocate",
    "_f_set_array_bounds",
    "_f_array_lbound",
    "_f_array_ubound",
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
    "_f_maxval", "_f_minval",
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
    "_f_selected_int_kind", "_f_selected_real_kind", "_f_selected_logical_kind",
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


def _f_elemental_subroutine(function, arguments, output_indices, output_dtypes, pure_output_indices=()):
    """Call a scalar elemental subroutine once per element, then copy back outputs.

    Input scalars expand over the common array shape; arrays must conform.
    Calls are performed in Fortran array element order.
    """
    arrays = [np.asarray(arg) if isinstance(arg, (list, tuple, np.ndarray)) else None
              for arg in arguments]
    shape = next(a.shape for a in arrays if a is not None)
    if any(a is not None and a.shape != shape for a in arrays):
        raise ValueError("elemental subroutine array arguments must be conformable")
    if any(arrays[i] is None for i in output_indices):
        raise ValueError("elemental subroutine outputs must be arrays for an array call")
    results = [np.empty(shape, dtype=dtype) for dtype in output_dtypes]
    for flat_index in range(int(np.prod(shape))):
        index = np.unravel_index(flat_index, shape, order='F')
        scalar_args = [None if i in pure_output_indices else
                       (arrays[i][index] if arrays[i] is not None else arg)
                       for i, arg in enumerate(arguments)]
        returned = function(*scalar_args)
        values = (returned,) if len(results) == 1 else returned
        for result, value in zip(results, values if results else ()):
            if result.dtype == object:
                import copy
                value = copy.deepcopy(value)
            result[index] = value
    # Retain ndarray identities and views, including strided actual arguments.
    for result_index, (position, result) in enumerate(zip(output_indices, results)):
        if isinstance(arguments[position], np.ndarray):
            arguments[position][...] = result
            result = arguments[position]
        results[result_index] = result
    return results[0] if len(results) == 1 else tuple(results) if results else None


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


def _f_adjustr(string):
    def adjust(text):
        text = str(text)
        return text.rstrip(' ').rjust(len(text))
    array = np.asarray(string, dtype=object)
    return adjust(array.item()) if array.ndim == 0 else np.vectorize(adjust, otypes=[object])(array)


def _f_scan(string, set, back=False, kind=4, *, verify=False):
    a, b, reverse = np.broadcast_arrays(np.asarray(string, dtype=object),
        np.asarray(set, dtype=object), np.asarray(back, dtype=bool))
    def find(text, chars, backwards):
        indices = range(len(str(text)) - 1, -1, -1) if backwards else range(len(str(text)))
        return next((i + 1 for i in indices if (str(text)[i] in str(chars)) != verify), 0)
    result = np.vectorize(find, otypes=[np.int64])(a, b, reverse)
    if int(kind) not in (1, 2, 4, 8):
        raise ValueError('SCAN/VERIFY requires a supported integer kind')
    result = result.astype(f'int{8 * int(kind)}')
    return result[()] if result.ndim == 0 else result


def _f_verify(string, set, back=False, kind=4):
    return _f_scan(string, set, back, kind, verify=True)


def _f_repeat(string, ncopies):
    if np.ndim(string) or np.ndim(ncopies) or int(ncopies) < 0:
        raise ValueError('REPEAT requires scalar arguments and nonnegative NCOPIES')
    return str(string) * int(ncopies)


def _f_product(array, dim=None, mask=None):
    array = np.asarray(array)
    if array.ndim == 0 or array.dtype.kind not in 'iufc':
        raise ValueError('PRODUCT requires a numeric array')
    # PRODUCT(ARRAY, MASK) is an alternative to PRODUCT(ARRAY, DIM, MASK).
    if dim is not None and np.asarray(dim).dtype.kind == 'b':
        if mask is not None:
            raise ValueError('PRODUCT MASK specified twice')
        mask, dim = dim, None
    axis = None
    if dim is not None:
        axis = int(dim) - 1
        if np.ndim(dim) or not 0 <= axis < array.ndim:
            raise ValueError('PRODUCT DIM out of range')
    if mask is not None:
        mask = np.asarray(mask, dtype=bool)
        if mask.ndim and mask.shape != array.shape:
            raise ValueError('PRODUCT MASK must be scalar or conformable')
        array = np.where(mask, array, np.ones((), dtype=array.dtype))
    return np.prod(array, axis=axis, dtype=array.dtype)


def _f_unpack(vector, mask, field):
    vector, mask, field = np.asarray(vector), np.asarray(mask, dtype=bool), np.asarray(field)
    if vector.ndim != 1 or mask.ndim == 0:
        raise ValueError('UNPACK requires a rank-one VECTOR and array MASK')
    if field.ndim and field.shape != mask.shape:
        raise ValueError('UNPACK FIELD must be scalar or conformable with MASK')
    selected = mask.ravel(order='F')
    n = int(np.count_nonzero(selected))
    if vector.size < n:
        raise ValueError('UNPACK VECTOR is too short')
    result = np.broadcast_to(field, mask.shape).astype(vector.dtype, copy=True).ravel(order='F').copy()
    result[selected] = vector[:n]
    return result.reshape(mask.shape, order='F')


def _f_shift(array, shift, dim, boundary, circular):
    array = np.asarray(array)
    axis = int(dim) - 1
    if array.ndim == 0 or np.ndim(dim) or not 0 <= axis < array.ndim:
        raise ValueError('SHIFT DIM out of range')
    values = np.moveaxis(array, axis, -1)
    shifts = np.asarray(shift)
    if shifts.dtype.kind not in 'iu' or (shifts.ndim and shifts.shape != values.shape[:-1]):
        raise ValueError('SHIFT must be integer scalar or conformable rank-minus-one array')
    shifts = np.broadcast_to(shifts, values.shape[:-1])
    if not circular:
        if boundary is None:
            boundary = False if array.dtype.kind == 'b' else 0
            if array.dtype.kind in 'US':
                boundary = ' ' * (array.dtype.itemsize // (4 if array.dtype.kind == 'U' else 1))
            elif array.dtype.kind == 'O':
                if array.size and isinstance(array.flat[0], str):
                    boundary = ' ' * len(array.flat[0])
                elif array.size:
                    raise ValueError('EOSHIFT requires BOUNDARY for derived-type arrays')
        boundary = np.asarray(boundary)
        if boundary.ndim and boundary.shape != values.shape[:-1]:
            raise ValueError('EOSHIFT BOUNDARY must be scalar or conformable')
        boundary = np.broadcast_to(boundary, values.shape[:-1])
    result = np.empty_like(values)
    n = values.shape[-1]
    for index in np.ndindex(values.shape[:-1]):
        distance = int(shifts[index])
        if circular:
            result[index] = np.roll(values[index], -distance)
        else:
            result[index] = boundary[index]
            if 0 <= distance < n:
                result[index][:n - distance] = values[index][distance:]
            elif -n < distance < 0:
                result[index][-distance:] = values[index][:n + distance]
    return np.moveaxis(result, -1, axis)


def _f_cshift(array, shift, dim=1):
    return _f_shift(array, shift, dim, None, True)


def _f_eoshift(array, shift, boundary=None, dim=1):
    return _f_shift(array, shift, dim, boundary, False)


def _f_pointer_associate(target, lower=None, rank=None):
    """Give each pointer its own bounds descriptor while retaining shared data."""
    if target is None:
        return None
    if not isinstance(target, np.ndarray):
        if lower is not None or (rank is not None and rank != 0):
            raise ValueError('array pointer association requires ndarray storage')
        return target
    if rank is not None and target.ndim != rank:
        raise ValueError('rank-changing pointer association is not yet supported')
    if lower is None:
        lower = _f_array_lower_bounds(target)
    return _f_set_array_bounds(target.view(), lower)


def _f_pointer_target(array, index):
    """Basic indexing with integer axes squeezed only after taking a view."""
    if not isinstance(array, np.ndarray):
        raise ValueError('pointer element targets require ndarray storage')
    indices = index if isinstance(index, tuple) else (index,)
    slices, scalar_axes = [], []
    for axis, item in enumerate(indices):
        if isinstance(item, (int, np.integer)):
            position = int(item)
            if position < 0:
                position += array.shape[axis]
            if not 0 <= position < array.shape[axis]:
                raise IndexError('pointer target subscript out of bounds')
            slices.append(slice(position, position + 1))
            scalar_axes.append(axis)
        elif isinstance(item, slice):
            slices.append(item)
        else:
            raise ValueError('vector-subscripted pointer targets are not supported')
    view = array[tuple(slices)]
    return np.squeeze(view, axis=tuple(scalar_axes)) if scalar_axes else view


_f_no_associated_target = object()


def _f_associated(pointer, target=_f_no_associated_target):
    if target is _f_no_associated_target:
        return pointer is not None
    if pointer is None or target is None:
        return False
    if isinstance(pointer, np.ndarray) and isinstance(target, np.ndarray):
        if pointer.size == 0 or target.size == 0:
            return False
        if pointer.shape != target.shape or pointer.dtype != target.dtype:
            return False
        if pointer.__array_interface__['data'][0] != target.__array_interface__['data'][0]:
            return False
        # Singleton dimensions have no second element whose stride matters.
        return all(size <= 1 or first == second
                   for size, first, second in zip(pointer.shape, pointer.strides, target.strides))
    if isinstance(pointer, np.ndarray) or isinstance(target, np.ndarray):
        return False
    if isinstance(pointer, (int, float, complex, bool, str, np.generic)) or isinstance(
            target, (int, float, complex, bool, str, np.generic)):
        raise ValueError('ASSOCIATED scalar targets require preserved storage, not Python values')
    return pointer is target


def _f_is_contiguous(array):
    if array is None:
        raise ValueError('IS_CONTIGUOUS requires associated storage')
    array = np.asarray(array)
    return bool(array.flags.f_contiguous or array.flags.c_contiguous)


def _f_contiguous_arguments(*specifications):
    """Supply contiguous temporaries; copy modified INOUT/OUT values back."""
    def decorate(function):
        signature = inspect.signature(function)
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            copies = []
            for name, writable in specifications:
                value = bound.arguments.get(name)
                if value is None:
                    continue
                original = np.asarray(value)
                if not _f_is_contiguous(original):
                    temporary = np.array(original, copy=True, order='F')
                    bound.arguments[name] = temporary
                    if writable:
                        copies.append((original, temporary))
            try:
                return function(*bound.args, **bound.kwargs)
            finally:
                for original, temporary in copies:
                    original[...] = temporary
        return wrapped
    return decorate


def _f_execute_command_line(command, wait=True, *, has_cmdstat=False):
    """Execute a synchronous shell command with inherited standard streams.

    Return (EXITSTAT, CMDSTAT, CMDMSG); None means do not change that output.
    CMDSTAT=1 denotes a Python shell-launch failure; codes/messages are not
    compiler-independent. A completed shell command's nonzero exit is not a
    shell-launch failure.
    """
    command_array = np.asarray(command)
    logical_wait = np.asarray(wait)
    if command_array.ndim != 0 or command_array.dtype.kind != 'U':
        raise TypeError('EXECUTE_COMMAND_LINE COMMAND requires scalar CHARACTER')
    if logical_wait.ndim != 0 or logical_wait.dtype.kind != 'b':
        raise TypeError('EXECUTE_COMMAND_LINE WAIT requires scalar LOGICAL')
    if not bool(logical_wait):
        raise NotImplementedError('asynchronous EXECUTE_COMMAND_LINE (WAIT=.FALSE.) is not supported')
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        result = subprocess.run(str(command_array.item()).rstrip(' '), shell=True, check=False)
    except (OSError, ValueError) as error:
        if not has_cmdstat:
            raise RuntimeError(f'EXECUTE_COMMAND_LINE could not launch shell: {error}') from error
        return None, 1, str(error)
    return result.returncode, 0, None


def _f_command_argument_count():
    return max(0, len(sys.argv) - 1)


def _f_get_command_argument(number, value_length=None):
    number = int(number)
    exists = 0 <= number < len(sys.argv)
    text = sys.argv[number] if exists else ''
    length = len(text)
    status = 0 if exists else 1
    if value_length is not None:
        if exists and length > value_length:
            status = -1
        text = _f_str_assign(text, value_length)
    return text, length, status


def _f_bits(operation, i, j=None, *, pos=None, length=None, shift=None, bits=32):
    """Elemental bit operations with an explicit two's-complement word width."""
    bits = int(bits)
    if bits not in (8, 16, 32, 64):
        raise ValueError('unsupported integer bit width')
    operands = [np.asarray(i, dtype=object)]
    second = j if j is not None else pos if pos is not None else shift
    if second is not None:
        operands.append(np.asarray(second, dtype=object))
    if length is not None:
        operands.append(np.asarray(length, dtype=object))
    operands = np.broadcast_arrays(*operands)
    mask = (1 << bits) - 1
    def apply(*values):
        value = int(values[0]) & mask
        other = int(values[1]) if len(values) > 1 else 0
        if operation in {'btest', 'ibset', 'ibclr'} and not 0 <= other < bits:
            raise ValueError('bit position out of range')
        if operation == 'btest':
            return bool(value & (1 << other))
        if operation == 'ibset': result = value | (1 << other)
        elif operation == 'ibclr': result = value & ~(1 << other)
        elif operation == 'ibits':
            size = int(values[2])
            if other < 0 or size < 0 or other + size > bits:
                raise ValueError('IBITS position/length out of range')
            result = (value >> other) & ((1 << size) - 1)
        elif operation == 'iand': result = value & other
        elif operation == 'ior': result = value | other
        elif operation == 'ieor': result = value ^ other
        elif operation in {'shiftl', 'shiftr'}:
            if not 0 <= other <= bits:
                raise ValueError('SHIFT count out of range')
            result = value << other if operation == 'shiftl' else value >> other
        else: raise ValueError('unsupported bit operation')
        result &= mask
        return result - (1 << bits) if result >= (1 << (bits - 1)) else result
    dtype = bool if operation == 'btest' else np.dtype(f'int{bits}')
    result = np.vectorize(apply, otypes=[dtype])(*operands)
    return result[()] if result.ndim == 0 else result


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


def _f_shape(source, kind=None):
    """Fortran SHAPE: integer extent vector, including an empty scalar shape."""
    if source is None:
        raise ValueError("SHAPE requires an allocated/associated source")
    kind = 4 if kind is None else int(kind)
    if kind not in (1, 2, 4, 8):
        raise ValueError("SHAPE KIND must be a supported integer kind (1, 2, 4, 8)")
    return np.asarray(np.asarray(source).shape, dtype=f"int{8 * kind}")


def _f_rank(a):
    """Fortran RANK returns zero for a scalar, including CHARACTER scalars."""
    if a is None:
        raise ValueError("RANK of an unallocated/disassociated object is not yet supported")
    return int(np.asarray(a).ndim)


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


_f_allocation_bounds = {}


def _f_set_array_bounds(array, lower):
    """Attach allocation bounds without changing NumPy's indexing or type.

    Weak references prevent stale metadata after deallocation or replacement,
    and guard against Python reusing the identity of a released array.
    """
    if isinstance(lower, (int, np.integer)):
        lower = (int(lower),) * np.ndim(array)
    lower = tuple(int(n) for n in lower)
    if not isinstance(array, np.ndarray) or len(lower) != array.ndim:
        raise ValueError('allocation bounds must match the array rank')
    key = id(array)
    if all(n == 1 for n in lower):
        _f_allocation_bounds.pop(key, None)
    else:
        def released(ref):
            entry = _f_allocation_bounds.get(key)
            if entry is not None and entry[0] is ref:
                _f_allocation_bounds.pop(key, None)
        _f_allocation_bounds[key] = (weakref.ref(array, released), lower)
    return array


def _f_array_lower_bounds(array):
    entry = _f_allocation_bounds.get(id(array))
    if entry is not None and entry[0]() is array:
        return entry[1]
    return (1,) * np.ndim(array)


def _f_array_bound(array, dim, upper):
    if array is None:
        raise ValueError('bounds of an unallocated array are undefined')
    shape = np.shape(array)
    lower = _f_array_lower_bounds(array)
    values = tuple((lo + size - 1 if size else 0) if upper else (lo if size else 1)
                   for lo, size in zip(lower, shape))
    if dim is None:
        return np.asarray(values, dtype=int)
    axis = int(dim) - 1
    if not 0 <= axis < len(shape):
        raise ValueError('bounds DIM is outside the array rank')
    return values[axis]


def _f_array_lbound(array, dim=None):
    return _f_array_bound(array, dim, False)


def _f_array_ubound(array, dim=None):
    return _f_array_bound(array, dim, True)


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


def _f_assign_array(lhs, rhs, lower_bounds=None):
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
        if arr.dtype == object:
            import copy
            arr = copy.deepcopy(arr)
        lower = lower_bounds if lower_bounds is not None else (_f_array_lower_bounds(rhs) if isinstance(rhs, np.ndarray) else (1,) * arr.ndim)
        return _f_set_array_bounds(arr, lower)
    lhs_arr = np.asarray(lhs)
    if arr.dtype == object:
        import copy
        if arr.ndim == 0 and lhs_arr.ndim > 0:
            for index in np.ndindex(lhs_arr.shape):
                lhs_arr[index] = copy.deepcopy(arr.item())
            return lhs
        arr = copy.deepcopy(arr)
    if arr.ndim == 0 and lhs_arr.ndim > 0:
        lhs_arr[...] = arr.item()
        return lhs
    if lhs_arr.shape != arr.shape or lhs_arr.dtype != arr.dtype:
        if lhs_arr.shape == arr.shape:
            lower = _f_array_lower_bounds(lhs)
        else:
            lower = lower_bounds if lower_bounds is not None else (_f_array_lower_bounds(rhs) if isinstance(rhs, np.ndarray) else (1,) * arr.ndim)
        return _f_set_array_bounds(arr, lower)
    lhs_arr[...] = arr
    return lhs


def merge(tsource, fsource, mask):
    """Elemental MERGE: all array arguments conform; scalars expand to that shape."""
    m = np.asarray(mask)
    shapes = [a.shape for a in (np.asarray(tsource), np.asarray(fsource), m) if a.ndim]
    if not shapes:
        return tsource if bool(m) else fsource
    if any(shape != shapes[0] for shape in shapes[1:]):
        raise ValueError('MERGE array arguments must be conformable')
    return np.where(m, tsource, fsource)


def pack(array, mask, vector=None):
    """Fortran PACK equivalent."""
    a = np.asarray(array)
    m = np.asarray(mask, dtype=bool)
    if m.ndim and m.shape != a.shape:
        raise ValueError('PACK MASK must be scalar or conformable')
    selected = a.ravel(order='F')[np.broadcast_to(m, a.shape).ravel(order='F')]
    if vector is not None:
        vector = np.asarray(vector)
        if vector.ndim != 1 or vector.size < selected.size:
            raise ValueError('PACK VECTOR must be rank one and large enough')
        result = vector.copy()
        result[:selected.size] = selected
        selected = result
    if selected.dtype == object:
        import copy
        selected = copy.deepcopy(selected)
    return selected


def _f_extended_type(parent_name, parent_type, bindings=()):
    """Keep inherited components and the explicit parent in one storage object."""
    from dataclasses import fields
    import copy

    def decorate(cls):
        inherited = tuple(dict.fromkeys(
            [f.name for f in fields(parent_type)]
            + list(getattr(parent_type, '_f_inherited_components', ()))))
        own = tuple(f.name for f in fields(cls) if f.name != parent_name)
        flat = tuple(getattr(parent_type, '_f_constructor_components',
                             tuple(f.name for f in fields(parent_type)))) + own
        cls._f_inherited_components = inherited
        cls._f_constructor_components = flat
        for name in inherited:
            def get(self, name=name):
                return getattr(getattr(self, parent_name), name)
            def set_value(self, value, name=name):
                setattr(getattr(self, parent_name), name, value)
            setattr(cls, name, property(get, set_value))
        for name in bindings:
            if name not in cls.__dict__:
                def forward(self, *args, _name=name, **kwargs):
                    return getattr(parent_type, _name)(self, *args, **kwargs)
                setattr(cls, name, forward)
        original_init = cls.__init__

        def initialize(self, *args, **kwargs):
            # Fortran constructors accept a parent value or inherited components.
            if args and not isinstance(args[0], parent_type):
                if len(args) > len(flat):
                    raise TypeError('too many extended-type constructor arguments')
                positional = dict(zip(flat, args))
                if positional.keys() & kwargs.keys():
                    raise TypeError('duplicate extended-type constructor component')
                kwargs = {**positional, **kwargs}
                args = ()
            inherited_values = {name: kwargs.pop(name) for name in inherited if name in kwargs}
            if inherited_values:
                if args or parent_name in kwargs:
                    raise TypeError('cannot specify both parent and inherited components')
                kwargs[parent_name] = parent_type(**inherited_values)
            original_init(self, *args, **kwargs)
            # Structure construction copies a parent value, not a reference to it.
            setattr(self, parent_name, copy.deepcopy(getattr(self, parent_name)))

        cls.__init__ = initialize
        return cls
    return decorate


def _f_component_array(obj, path, dtype=None):
    """Project scalar components while retaining the parent array's shape."""
    array = np.asarray(obj, dtype=object)
    values = []
    for item in array.flat:
        for attr in path.split('.'):
            item = getattr(item, attr)
        if np.ndim(item) != 0:
            raise ValueError('array components of an array parent require explicit subscripts')
        values.append(item)
    return np.asarray(values, dtype=dtype).reshape(array.shape)


def _f_assign_component_array(obj, path, value, mask=None):
    """Scatter a scalar or conformable RHS into derived-type components."""
    import copy
    array = np.asarray(obj, dtype=object)
    rhs = np.asarray(value)
    if rhs.ndim and rhs.shape != array.shape:
        raise ValueError('component assignment requires scalar or conformable RHS')
    rhs = np.broadcast_to(rhs, array.shape)
    if mask is None:
        selected = np.ones(array.shape, dtype=bool)
    else:
        selected = np.asarray(mask, dtype=bool)
        if selected.ndim and selected.shape != array.shape:
            raise ValueError('component assignment MASK must be scalar or conformable')
        selected = np.broadcast_to(selected, array.shape)
    attrs = path.split('.')
    # Snapshot every value before mutation, preserving Fortran RHS evaluation.
    values = [copy.deepcopy(value) for value in rhs.flat]
    for item, value, active in zip(array.flat, values, selected.flat):
        if active:
            for attr in attrs[:-1]:
                item = getattr(item, attr)
            setattr(item, attrs[-1], value)


def count(x):
    """Count non-zero/true entries."""
    return int(np.count_nonzero(np.asarray(x)))


def _f_extreme(x, dim, mask, *, minimum, integer_kind):
    name = "MINVAL" if minimum else "MAXVAL"
    a = np.asarray(x)
    if a.ndim == 0 or a.dtype.kind not in "iuf":
        raise TypeError(f"{name} currently requires an INTEGER or REAL array")
    # MAXVAL/MINVAL(ARRAY, MASK) is an alternative positional form.
    if dim is not None and np.asarray(dim).dtype.kind == "b":
        if mask is not None:
            raise ValueError(f"{name} MASK specified twice")
        mask, dim = dim, None
    axis = None
    if dim is not None:
        dimension = np.asarray(dim)
        if dimension.ndim or dimension.dtype.kind not in "iu" or not 1 <= int(dim) <= a.ndim:
            raise ValueError(f"{name} DIM must be a scalar integer between 1 and array rank")
        axis = int(dim) - 1
    selected = np.asarray(True if mask is None else mask)
    if selected.dtype.kind != "b" or (selected.ndim and selected.shape != a.shape):
        raise ValueError(f"{name} MASK must be logical and scalar or conformable")
    selected = np.broadcast_to(selected, a.shape)
    if a.dtype.kind in "iu":
        info = np.iinfo(a.dtype)
        identity = info.max if minimum else info.min
        huge_value = (_f_numeric_model(None, "huge", integer_kind=integer_kind)
                      if integer_kind is not None else info.max)
        empty_value = huge_value if minimum else (0 if a.dtype.kind == "u" else -huge_value)
    else:
        identity = np.inf if minimum else -np.inf
        empty_value = np.finfo(a.dtype).max * (1 if minimum else -1)
    reduction = np.min if minimum else np.max
    result = reduction(a, axis=axis, where=selected, initial=identity)
    # Finite +/-HUGE is the Fortran empty result, but it must not hide
    # selected infinities or the most-negative representable integer.
    result = np.where(np.any(selected, axis=axis), result, empty_value).astype(a.dtype)
    return result[()] if result.ndim == 0 else result


def maxval(x, dim=None, mask=None, *, integer_kind=None):
    """Fortran numeric MAXVAL with one-based DIM and conformable MASK."""
    return _f_extreme(x, dim, mask, minimum=False, integer_kind=integer_kind)


def minval(x, dim=None, mask=None, *, integer_kind=None):
    """Fortran numeric MINVAL with one-based DIM and conformable MASK."""
    return _f_extreme(x, dim, mask, minimum=True, integer_kind=integer_kind)


_f_maxval = maxval
_f_minval = minval


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


def _f_kind_request(value, name):
    """Kind selection arguments must be scalar integers, not rounded reals."""
    value = np.asarray(value)
    if value.ndim != 0 or value.dtype.kind not in 'iu':
        raise TypeError(f'{name} requires a scalar INTEGER argument')
    return int(value)


def _f_selected_int_kind(r):
    """Select among supported byte kinds 1, 2, 4, 8 (not a host compiler query)."""
    r = _f_kind_request(r, 'SELECTED_INT_KIND R')
    for kind, decimal_range in ((1, 2), (2, 4), (4, 9), (8, 18)):
        if r <= decimal_range:
            return kind
    return -1


def _f_selected_logical_kind(bits):
    bits = _f_kind_request(bits, 'SELECTED_LOGICAL_KIND BITS')
    return next((kind for kind in (1, 2, 4, 8) if 8 * kind >= bits), -1)


def _f_selected_real_kind(p=0, r=0, radix=None):
    """Select IEEE binary32/binary64; extended real kinds are not supported."""
    p = _f_kind_request(p, 'SELECTED_REAL_KIND P')
    r = _f_kind_request(r, 'SELECTED_REAL_KIND R')
    if radix is not None and _f_kind_request(radix, 'SELECTED_REAL_KIND RADIX') != 2:
        return -5
    models = ((4, 6, 37), (8, 15, 307))
    for kind, precision, decimal_range in models:
        if p <= precision and r <= decimal_range:
            return kind
    precision_available = any(p <= precision for _, precision, _ in models)
    range_available = any(r <= decimal_range for _, _, decimal_range in models)
    if not precision_available and not range_available:
        return -3
    if not precision_available:
        return -1
    if not range_available:
        return -2
    return -4


def _f_numeric_model(x, inquiry, *, integer_kind=None):
    # Model inquiries depend on the declared type/kind, not the value.
    # Plain Python integers and initialized ndarray storage can lose that
    # information; the translator supplies it when it is known.
    if integer_kind is not None:
        if integer_kind == 16:
            # NumPy has no signed int128 dtype. These inquiries describe the
            # declared 128-bit model and do not need storage of that dtype.
            models = {"huge": (1 << 127) - 1, "digits": 127, "range": 38, "radix": 2}
            if inquiry in models:
                return models[inquiry]
            raise TypeError(f"{inquiry.upper()} requires REAL or COMPLEX input")
        if integer_kind not in (1, 2, 4, 8):
            raise ValueError(f"unsupported Fortran integer kind for {inquiry.upper()}: {integer_kind}")
        dtype = np.dtype(f"int{8 * int(integer_kind)}")
    else:
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
