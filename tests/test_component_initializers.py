from dataclasses import dataclass, field

import numpy as np
import pytest

from fortran_py_runtime import _f_init_component_array
from xf2p import basic_f2p


@pytest.mark.parametrize("shape, initializer, dtype, expected", [
    ((3,), 2, int, [2,2,2]),
    ((2,), [1.9,-1.9], int, [1,-1]),
    ((2,2), [[1,2],[3,4]], float, [[1.,2.],[3.,4.]]),
    ((2,), [True,False], bool, [True,False]),
    ((0,2), 7, int, []),
])
def test_component_array_shape_type_and_values(shape, initializer, dtype, expected):
    actual = _f_init_component_array(shape, initializer, dtype)
    assert actual.shape == shape
    assert actual.dtype == np.dtype(dtype)
    assert actual.tolist() == expected


def test_component_array_copies_each_derived_element():
    @dataclass
    class Leaf:
        values: list = field(default_factory=lambda: [3,4])
    initializer = Leaf()
    a = _f_init_component_array((2,), initializer, object)
    b = _f_init_component_array((2,), initializer, object)
    a[0].values[0] = 99
    assert a[1].values == b[0].values == initializer.values == [3,4]
    assert a[0] is not a[1]


def test_generated_factory_does_not_alias_parameter_or_other_instances():
    source = """module m
integer, parameter :: seed(2) = [2,4]
type :: record
integer :: samples(2) = seed
end type record
end module m
"""
    namespace = {"__name__": "test_components"}
    exec(basic_f2p().transpile(source), namespace)
    a, b = namespace["record"](), namespace["record"]()
    assert a.samples.tolist() == b.samples.tolist() == [2,4]
    a.samples[0] = 99
    assert b.samples.tolist() == [2,4]
    assert namespace["seed"].tolist() == [2,4]
