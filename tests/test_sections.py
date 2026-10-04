import numpy as np
import pytest

from fortran_py_runtime import _f_section_slice
from xf2p import basic_f2p


def test_nested_section_bound_is_not_split_inside_parentheses():
    assert basic_f2p._split_section("sum(a(:)):n:2") == ("sum(a(:))", "n:2")
    assert basic_f2p._split_section(":") == ("", "")
    assert basic_f2p._split_section("5:") == ("5", "")
    assert basic_f2p._split_section("::2") == ("", ":2")


@pytest.mark.parametrize("lower, upper, stride, expected", [
    (None, None, 1, [10,11,12,13,14,15]),
    (None, None, -1, []),
    (5, 0, -1, [15,14,13,12,11,10]),
    (5, 0, -2, [15,13,11]),
    (None, 0, -2, [10]),
    (5, None, -2, [15]),
    (0, 5, 2, [10,12,14]),
    (0, 5, -1, []),
    (5, 0, 1, []),
    (5, -1, -4, [15,11]),
])
def test_fortran_triplet(lower, upper, stride, expected):
    a = np.arange(10,16)
    assert a[_f_section_slice(a, 0, 0, lower, upper, stride)].tolist() == expected


def test_stride_zero_rejected():
    with pytest.raises(ValueError, match="zero"):
        _f_section_slice(np.arange(3), 0, 1, stride=0)


def test_nonempty_out_of_bounds_rejected():
    with pytest.raises(IndexError):
        _f_section_slice(np.arange(3), 0, 1, 0, 2, 1)


def test_empty_array_forward():
    a = np.array([], dtype=int)
    assert a[_f_section_slice(a, 0, 1, stride=1)].size == 0
