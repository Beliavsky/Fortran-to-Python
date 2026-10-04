import numpy as np
import pytest

from fortran_py_runtime import (_f_fraction, _f_exponent, _f_scale,
    _f_set_exponent, _f_nearest, _f_spacing, _f_rrspacing,
    _f_numeric_model, _f_dim, _f_sign)


@pytest.mark.parametrize('dtype', [np.float32, np.float64])
def test_decomposition_and_spacing(dtype):
    info = np.finfo(dtype)
    x = np.array([0, 1, -1, .7, 8], dtype=dtype)
    fraction, exponent = _f_fraction(x), _f_exponent(x)
    assert np.array_equal(_f_scale(fraction, exponent), x)
    assert fraction.dtype == np.dtype(dtype)
    assert _f_set_exponent(dtype(8), 1) == 1
    assert _f_set_exponent(dtype(0), 20) == 0
    assert _f_spacing(dtype(0)) == info.tiny
    assert _f_spacing(dtype(1)) == info.eps
    assert _f_spacing(dtype(-1)) == info.eps
    assert _f_spacing(dtype(info.smallest_subnormal)) == info.tiny
    assert _f_rrspacing(dtype(0)) == 0
    assert _f_rrspacing(dtype(1)) == 2 ** info.nmant


@pytest.mark.parametrize('dtype', [np.float32, np.float64])
def test_neighbors_and_numeric_model(dtype):
    info = np.finfo(dtype)
    assert _f_nearest(dtype(1), dtype(1)) == dtype(1) + info.eps
    assert _f_nearest(dtype(1), dtype(-1)) == dtype(1) - info.eps / 2
    assert _f_nearest(dtype(0), dtype(1)) == info.smallest_subnormal
    assert _f_nearest(dtype(0), dtype(-1)) == -info.smallest_subnormal
    assert _f_nearest(np.array([0, 1], dtype=dtype), dtype(1)).dtype == np.dtype(dtype)
    with pytest.raises(ValueError, match='nonzero'):
        _f_nearest(dtype(1), dtype(0))
    expected = dict(tiny=info.tiny, huge=info.max, digits=info.nmant+1,
                    precision=info.precision, radix=2,
                    range=37 if dtype == np.float32 else 307)
    for name, value in expected.items():
        assert _f_numeric_model(dtype(1), name) == value


def test_integer_model_and_elemental_numeric_functions():
    assert _f_numeric_model(np.int32(0), 'digits') == 31
    assert _f_numeric_model(np.int64(0), 'range') == 18
    assert _f_numeric_model(np.int32(0), 'huge') == 2147483647
    assert _f_dim([1, 4, -1], [3, 2, -3]).tolist() == [0, 2, 2]
    assert _f_sign([1, -2, 3], [-1, -1, 0]).tolist() == [-1, -2, 3]
    assert _f_sign(np.array([1, 2], dtype=np.int32), -1).dtype == np.dtype('int32')
    assert np.signbit(_f_sign(0., -1.))
    assert _f_sign(2., -0.) == -2.
