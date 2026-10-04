import numpy as np
import pytest

from xf2p import basic_f2p


@pytest.mark.parametrize("expression, expected", [
    ("[(1d0,2d0),(-3d0,4d0)]", [1+2j,-3+4j]),
    ("[complex :: (1d0,2d0),(-3d0,4d0)]", [1+2j,-3+4j]),
    ("[(1d0,2d0)+(3d0,4d0)]", [4+6j]),
    ("[conjg((1d0,2d0))]", [1-2j]),
    ("reshape([(1d0,2d0),(-3d0,4d0)],[1,2])", [[1+2j,-3+4j]]),
])
def test_complex_constructor_elements(expression, expected):
    source = f"program test\ncomplex(kind=kind(1d0)) :: z(2)\nz = {expression}\nend program test\n"
    namespace = {"__name__": "test_components"}
    exec(basic_f2p().transpile(source), namespace)
    actual = eval(basic_f2p().translate_expr(expression, set()), namespace)
    np.testing.assert_array_equal(actual, expected)


def test_keyword_constructor_preserves_complex_values():
    translator = basic_f2p()
    actual = translator.translate_expr("inspect(values=[(1d0,2d0),(-3d0,4d0)])", set())
    namespace = {"np": np, "_xf2p_cmplx": complex, "inspect": lambda values: values}
    np.testing.assert_array_equal(eval(actual, namespace), [1+2j,-3+4j])


def test_parentheses_in_strings_are_not_complex_literals():
    translated = basic_f2p().translate_expr("['(1,2)','foo(3,4)']", set())
    assert eval(translated, {"np": np}).tolist() == ["(1,2)","foo(3,4)"]


def test_chained_component_read_is_indexed_twice():
    translated = basic_f2p().translate_expr("a%copies(1)%values(2)", set())
    assert translated == "a.copies[1 - 1].values[2 - 1]"
