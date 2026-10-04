from dataclasses import dataclass

import numpy as np
import pytest

from fortran_py_runtime import _f_allocate
from xf2p import basic_f2p


def test_source_copies_data_without_aliasing():
    source = np.array([[1.,2.],[3.,4.]])
    result = _f_allocate(source, dtype=float, source=True, rank=2)
    np.testing.assert_array_equal(result, source)
    result[0,0] = 99
    assert source[0,0] == 1


def test_mold_reads_shape_not_values():
    class ShapeOnly(np.ndarray):
        def __array__(self, *args, **kwargs):
            raise AssertionError("MOLD values must not be converted")
    model = np.empty((2,3)).view(ShapeOnly)
    result = _f_allocate(model, dtype=complex, rank=2)
    assert result.shape == (2,3)
    assert result.dtype == complex


def test_source_scalar_expansion_and_empty_shape():
    assert _f_allocate(7, shape=(3,), dtype=int, source=True).tolist() == [7,7,7]
    assert _f_allocate(7, shape=(0,), dtype=int, source=True).shape == (0,)


def test_source_array_shape_is_not_broadcast():
    with pytest.raises(ValueError, match="shape"):
        _f_allocate([1,2], shape=(2,2), dtype=int, source=True, rank=2)


def test_mold_derived_defaults_not_source_values():
    @dataclass
    class Leaf:
        value: int = 4
    result = _f_allocate(Leaf(99), shape=(2,), dtype=object, factory=Leaf)
    assert result[0].value == result[1].value == 4
    assert result[0] is not result[1]


@pytest.mark.parametrize("statement", [
    "allocate(y,source=x,mold=x)", "allocate(y,unknown=1)",
    "allocate(real :: y(3))", "allocate(y,errmsg=message)",
])
def test_unsupported_allocation_options_are_not_silently_mistranslated(statement):
    translator = basic_f2p()
    translator._decl_types = {"y": "real"}
    translator._decl_array_types = {"y": "real"}
    translator._decl_lbounds = {"y": ["1"]}
    with pytest.raises(ValueError):
        translator.handle_exec_line(statement, {"y"})
