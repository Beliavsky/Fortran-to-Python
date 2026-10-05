import numpy as np
import pytest

from fortran_py_runtime import merge


@pytest.mark.parametrize('shape', [(3,), (2,3), (2,1,3), (0,), (2,0,3)])
@pytest.mark.parametrize('mask', [True, False])
@pytest.mark.parametrize('array_first', [True, False])
def test_scalar_mask_preserves_array_shape(shape, mask, array_first):
    array = np.arange(np.prod(shape)).reshape(shape)
    tsource, fsource = (array, 10) if array_first else (10, array)
    result = merge(tsource, fsource, mask)
    expected = np.where(mask, tsource, fsource)
    assert np.shape(result) == shape
    np.testing.assert_array_equal(result, expected)


@pytest.mark.parametrize('value', [3, 2.5, 1+2j, True, 'abcd'])
@pytest.mark.parametrize('mask', [True, False])
def test_scalar_sources_keep_scalar_result(value, mask):
    result = merge(value, value, mask)
    assert np.ndim(result) == 0
    assert result == value


@pytest.mark.parametrize('values, scalar', [
    ([1.,2.,3.], 4.), ([1+2j,3+4j], 5+6j),
    ([True,False], True), (['abcd','efgh'], 'ijkl'),
])
def test_array_sources_with_scalar_mask_for_other_types(values, scalar):
    array = np.asarray(values)
    result = merge(scalar, array, True)
    assert result.shape == array.shape
    np.testing.assert_array_equal(result, np.full(array.shape, scalar))
    result = merge(array, scalar, False)
    assert result.shape == array.shape
    np.testing.assert_array_equal(result, np.full(array.shape, scalar))


def test_array_mask_expands_two_scalar_sources():
    mask = np.array([[True,False],[False,True]])
    result = merge(10, 20, mask)
    np.testing.assert_array_equal(result, [[10,20],[20,10]])


@pytest.mark.parametrize('tsource, fsource, mask', [
    (np.zeros((2,3)), np.ones((1,3)), True),
    (np.zeros((2,3)), 10, np.ones((3,), dtype=bool)),
    (10, np.zeros((2,3)), np.ones((2,1), dtype=bool)),
])
def test_arrays_must_conform_instead_of_using_numpy_broadcasting(tsource, fsource, mask):
    with pytest.raises(ValueError, match='conformable'):
        merge(tsource, fsource, mask)


def test_array_merge_result_does_not_alias_selected_source():
    source = np.array([1,2,3])
    result = merge(source, 0, True)
    result[0] = 99
    assert source.tolist() == [1,2,3]
