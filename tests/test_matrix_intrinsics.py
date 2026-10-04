import numpy as np
import pytest

from fortran_py_runtime import _f_dot_product, _f_reshape, matmul


def test_complex_dot_product_conjugates_first_vector():
    a = np.array([1+2j,3-1j])
    b = np.array([-2+1j,4+3j])
    assert _f_dot_product(a,b) == np.sum(np.conjugate(a)*b)
    assert _f_dot_product(a,b) != np.dot(a,b)


def test_logical_dot_product_and_empty_vectors():
    assert _f_dot_product([True,False], [True,True])
    assert not _f_dot_product([True,False], [False,True])
    assert not _f_dot_product(np.array([], dtype=bool), np.array([], dtype=bool))
    assert _f_dot_product(np.array([], dtype=int), np.array([], dtype=int)) == 0


@pytest.mark.parametrize("a,b", [([[1,2]], [1,2]), ([1], [1,2])])
def test_dot_product_shape_validation(a,b):
    with pytest.raises(ValueError):
        _f_dot_product(a,b)


def test_logical_matmul_result_is_boolean():
    a = np.ones((2,3), dtype=bool)
    b = np.ones((3,2), dtype=bool)
    result = matmul(a,b)
    assert result.dtype == np.bool_
    assert result.all()
    assert matmul(a,np.ones(3,dtype=bool)).all()
    assert matmul(np.ones(3,dtype=bool),b).all()


def test_fortran_reshape_order_and_padding():
    assert _f_reshape([1,2,3,4,5,6], [2,3]).tolist() == [[1,3,5],[2,4,6]]
    assert _f_reshape([1,2,3,4,5,6], [2,3], order=[2,1]).tolist() == [[1,2,3],[4,5,6]]
    assert _f_reshape([1,2], [2,3], pad=[9,8]).tolist() == [[1,9,9],[2,8,8]]
    assert _f_reshape(np.array([[1,3],[2,4]]), [4]).tolist() == [1,2,3,4]


def test_fortran_reshape_empty_and_invalid_arguments():
    assert _f_reshape([], [0,2]).shape == (0,2)
    with pytest.raises(ValueError):
        _f_reshape([1], [2])
    with pytest.raises(ValueError):
        _f_reshape([1,2], [1,2], order=[1,1])
