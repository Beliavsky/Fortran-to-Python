from pathlib import Path

import numpy as np
import pytest

import fortran_py_runtime as runtime
from fortran_py_runtime import maxval, minval
from xf2p import basic_f2p


@pytest.mark.parametrize("function, reference", [(maxval, np.max), (minval, np.min)])
@pytest.mark.parametrize("dtype", [np.int16, np.int32, np.int64, np.float32, np.float64])
def test_dimensional_reductions(function, reference, dtype):
    a = np.array([[5, 1, 7], [2, 9, 3]], dtype=dtype)
    for dim in [None, 1, 2]:
        actual = function(a, dim)
        expected = reference(a, axis=None if dim is None else dim - 1)
        np.testing.assert_array_equal(actual, expected)
        assert np.asarray(actual).dtype == a.dtype


@pytest.mark.parametrize("function, sign", [(maxval, -1), (minval, 1)])
@pytest.mark.parametrize("dtype", [np.int16, np.int32, np.int64, np.float32, np.float64])
def test_masks_and_empty_slices(function, sign, dtype):
    a = np.array([[5, 1, 7], [2, 9, 3]], dtype=dtype)
    huge = np.iinfo(dtype).max if np.dtype(dtype).kind == "i" else np.finfo(dtype).max
    mask = np.array([[True, False, True], [False, False, True]])
    expected = [5, sign * huge, 7 if function is maxval else 3]
    np.testing.assert_array_equal(function(a, 1, mask), np.array(expected, dtype=dtype))
    assert function(a, False) == sign * huge
    assert function(np.empty((0, 2), dtype=dtype)) == sign * huge
    np.testing.assert_array_equal(function(np.empty((0, 2), dtype=dtype), 1),
                                  np.full(2, sign * huge, dtype=dtype))
    assert function(np.empty((0, 2), dtype=dtype), 2).shape == (0,)
    assert function(a, mask) == function(a, mask=mask)


def test_extreme_selected_values_not_hidden_by_empty_identity():
    assert maxval(np.array([-128], dtype=np.int8)) == -128
    assert minval(np.array([np.inf])) == np.inf
    assert maxval(np.array([-np.inf])) == -np.inf
    assert maxval(np.array([], dtype=np.int64), integer_kind=4) == -2147483647
    assert minval(np.array([], dtype=np.int64), integer_kind=4) == 2147483647


def test_nested_reduction_keeps_empty_integer_kind(capsys):
    source = ("program demo\ninteger :: a(2,0)\n"
              "print *, minval(maxval(a,dim=1))\nend program")
    exec(basic_f2p().transpile(source), {"__name__": "__main__"})
    assert capsys.readouterr().out.strip() == "2147483647"


@pytest.mark.parametrize("expression", ["maxval()", "minval(a,dim=1,dim=2)",
                                          "maxval(a,bogus=1)", "minval(array=a,2)"])
def test_invalid_intrinsic_arguments_rejected(expression):
    with pytest.raises(ValueError, match="MAXVAL|MINVAL"):
        basic_f2p().translate_expr(expression, {"a"})


@pytest.mark.parametrize("function", [maxval, minval])
@pytest.mark.parametrize("dim", [0, 3, 1.5, np.array([1])])
def test_invalid_dimension_rejected(function, dim):
    with pytest.raises(ValueError, match="DIM"):
        function(np.zeros((2, 3)), dim)


@pytest.mark.parametrize("function", [maxval, minval])
@pytest.mark.parametrize("mask", [np.ones((1, 3), dtype=bool), [1, 0], 1])
def test_nonconformable_or_nonlogical_mask_rejected(function, mask):
    with pytest.raises(ValueError, match="MASK"):
        function(np.zeros((2, 3)), mask=mask)


@pytest.mark.parametrize("expression, expected", [
    ("maxval(a,1)", [5, 9, 7]),
    ("minval(a,2)", [1, 2]),
    ("maxval(a,dim=1)", [5, 9, 7]),
    ("minval(array=a,dim=2)", [1, 2]),
    ("maxval(mask=a<7,array=a,dim=1)", [5, 1, 3]),
    ("minval(a,a>2)", 3),
    ("maxval(a,2,a<7)", [5, 3]),
    ("sqrt(maxval(a,1))", np.sqrt([5, 9, 7])),
    ("minval(maxval(a,1))", 5),
    ("sum(maxval(a,dim=1))", 21),
])
def test_translation_preserves_arguments_and_nested_dimensions(expression, expected):
    a = np.array([[5, 1, 7], [2, 9, 3]])
    translator = basic_f2p()
    generated = expression
    for _ in range(3):
        generated = translator.translate_expr(generated, {"a"})
        actual = eval(generated, {**vars(runtime), "np": np, "a": a})
        np.testing.assert_allclose(actual, expected)


def test_native_extreme_reduction_fixture(capsys):
    source = (Path(__file__).parent / "cases/features/extreme_reductions.f90").read_text()
    exec(basic_f2p().transpile(source), {"__name__": "__main__"})
    assert "extreme reduction checks passed" in capsys.readouterr().out


def test_intrinsic_names_inside_labels_are_unchanged(capsys):
    source = "program demo\nprint *, 'maxval(a,1) minval(a,mask)'\nend program"
    exec(basic_f2p().transpile(source), {"__name__": "__main__"})
    assert capsys.readouterr().out.strip() == "maxval(a,1) minval(a,mask)"
