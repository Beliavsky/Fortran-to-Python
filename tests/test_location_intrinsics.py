import numpy as np
import pytest

from fortran_py_runtime import _f_minloc, _f_maxloc, _f_findloc


def test_vector_locations_and_back():
    v = [2, 4, 6, -1, 4]
    assert _f_minloc(v).tolist() == [4]
    assert _f_maxloc(v).tolist() == [3]
    assert _f_findloc(v, 4).tolist() == [2]
    assert _f_findloc(v, 4, back=True).tolist() == [5]
    assert _f_findloc(v, 5).tolist() == [0]
    assert _f_minloc([1, 1], back=True).tolist() == [2]


def test_matrix_order_and_dim():
    a = np.array([[4, 1, 6], [1, 6, 1]])
    assert _f_minloc(a).tolist() == [2, 1]
    assert _f_minloc(a, back=True).tolist() == [2, 3]
    assert _f_maxloc(a).tolist() == [2, 2]
    assert _f_minloc(a, dim=1).tolist() == [2, 1, 2]
    assert _f_findloc(a, 6, dim=2).tolist() == [3, 2]
    assert _f_minloc(a.astype(float), dim=1, mask=[[True, False, True], [False, False, True]]).tolist() == [1, 0, 2]
    cube = np.zeros((2, 3, 4))
    cube[1, 0, 2] = -1.5
    assert _f_minloc(cube).tolist() == [2, 1, 3]
    assert np.ndim(_f_minloc([3, 1], dim=1)) == 0


def test_masks_empty_arrays_and_kinds():
    assert _f_maxloc([1, 2], mask=False).tolist() == [0]
    assert _f_findloc([], 1).tolist() == [0]
    assert _f_minloc(np.empty((0, 3)), dim=1).tolist() == [0, 0, 0]
    assert _f_minloc([1, 2], [False, True], kind=8).tolist() == [2]
    assert _f_maxloc([2, 2], True, 4, True).tolist() == [2]
    assert _f_minloc([1], kind=4).dtype == np.dtype("int32")
    with pytest.raises(ValueError, match="conform"):
        _f_minloc([1, 2], mask=[True])
    with pytest.raises(ValueError, match="DIM"):
        _f_minloc([1, 2], dim=2)


def test_character_and_logical_findloc():
    assert _f_minloc(["b", "a ", "a"], back=True).tolist() == [3]
    assert _f_maxloc(["b", "a ", "a"]).tolist() == [1]
    assert _f_findloc(["a ", "b"], "a").tolist() == [1]
    assert _f_findloc([False, True, True], True, back=True).tolist() == [3]
