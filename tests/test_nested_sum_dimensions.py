import numpy as np
import pytest

import fortran_py_runtime as runtime
from xf2p import basic_f2p


@pytest.mark.parametrize('expression, expected', [
    ('sqrt(sum(a, dim=1))', np.sqrt([3,7,11])),
    ('sqrt(sum(a, dim=2))', np.sqrt([9,12])),
    ('sum(sum(a, dim=1))', 21),
    ('sum(sum(a, dim=2))', 21),
    ('sum(sum(a, dim=1)**2)', 179),
    ('sqrt(sum(a, dim=1, mask=a>2))', np.sqrt([0,7,11])),
    ('sqrt(sum(a, mask=a>2, dim=2))', np.sqrt([8,10])),
])
def test_nested_sum_keeps_dimension(expression, expected):
    translator = basic_f2p()
    a = np.arange(1,7).reshape((2,3), order='F')
    generated = translator.translate_expr(expression, {'a'})
    actual = eval(generated, {**vars(runtime), 'np': np, 'a': a})
    assert np.shape(actual) == np.shape(expected)
    np.testing.assert_allclose(actual, expected, rtol=1e-12)


@pytest.mark.parametrize('axis', [0, 1])
def test_already_lowered_sum_axis_is_not_dropped_or_shifted(axis):
    translator = basic_f2p()
    a = np.arange(6).reshape((2,3))
    generated = translator.translate_expr(f'np.sum(a, axis={axis})', {'a'})
    actual = eval(generated, {'np': np, 'a': a})
    np.testing.assert_array_equal(actual, np.sum(a, axis=axis))


def test_repeated_translation_preserves_reduction_axis():
    translator = basic_f2p()
    a = np.arange(1,7).reshape((2,3), order='F')
    generated = 'sqrt(sum(a, dim=1))'
    for _ in range(3):
        generated = translator.translate_expr(generated, {'a'})
        np.testing.assert_allclose(eval(generated, {'np': np, 'a': a}), np.sqrt([3,7,11]))


@pytest.mark.parametrize('dimension', [1,2])
def test_variable_sum_dimension_is_converted_only_once(dimension):
    a = np.arange(1,7).reshape((2,3), order='F')
    generated = basic_f2p().translate_expr('sqrt(sum(a, dim=d))', {'a'})
    actual = eval(generated, {'np': np, 'a': a, 'd': dimension})
    np.testing.assert_allclose(actual, np.sqrt(np.sum(a, axis=dimension-1)))


def test_two_nested_dimensional_reductions_of_rank_three_array():
    b = np.arange(1,25).reshape((2,3,4), order='F')
    generated = basic_f2p().translate_expr('sum(sum(b, dim=1), dim=2)', {'b'})
    actual = eval(generated, {'np': np, 'b': b})
    expected = np.sum(np.sum(b, axis=0), axis=1)
    assert actual.shape == expected.shape
    np.testing.assert_array_equal(actual, expected)
