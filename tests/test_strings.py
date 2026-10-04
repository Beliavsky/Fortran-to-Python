import numpy as np
import pytest

from fortran_py_runtime import _f_str_assign, _f_len_trim, _f_adjustl, _f_index


@pytest.mark.parametrize("value,length,expected", [
    ("hello", 8, "hello   "), ("hello", 3, "hel"),
    ("", 3, "   "), ("hi", 0, ""), ("  hi ", 5, "  hi "),
])
def test_fixed_length_assignment(value,length,expected):
    assert _f_str_assign(value,length) == expected


def test_array_assignment_and_empty_arrays():
    assert _f_str_assign(["a", "abcdef"],3).tolist() == ["a  ", "abc"]
    result = _f_str_assign(np.empty((0,2),dtype=object),4)
    assert result.shape == (0,2)


def test_blanks_are_not_arbitrary_whitespace():
    assert _f_len_trim("x\t ") == 2
    assert _f_adjustl(" \tx ") == "\tx  "
    assert _f_len_trim(["a  ", "ab "]).tolist() == [1,2]
    assert _f_adjustl([" a ","   "]).tolist() == ["a  ","   "]


def test_index_positions_and_broadcasting():
    assert _f_index("banana", "an") == 2
    assert _f_index("banana", "an",True) == 4
    assert _f_index("banana", "x") == 0
    assert _f_index("abc", "") == 1
    assert _f_index("abc", "",True) == 4
    assert _f_index(["banana","apple"],"a").tolist() == [2,1]


def test_empty_elemental_strings():
    a = np.empty((0,2),dtype=object)
    assert _f_len_trim(a).shape == a.shape
    assert _f_adjustl(a).shape == a.shape
    assert _f_index(a,"x").shape == a.shape
