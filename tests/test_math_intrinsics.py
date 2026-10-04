import numpy as np
import pytest

from xf2p import basic_f2p
from fortran_py_runtime import _f_epsilon, _f_norm2, _f_sinpi, _f_cospi, _f_tanpi


def test_tan_is_numpy_only_and_preserves_labels(capsys):
    generated = basic_f2p().transpile("program demo\nprint *, TAN(0d0)\nprint *, 'tan(0.0)'\nend program")
    assert 'np.tan(' in generated
    assert 'import scipy' not in generated
    namespace = {'__name__': 'tan_test'}
    exec(generated, namespace)
    namespace['main']()
    assert capsys.readouterr().out.split() == ['0.0', 'tan(0.0)']


def test_norm2_is_scaled_and_dimension_aware():
    assert np.isclose(_f_norm2(np.array([3e200, 4e200])), 5e200)
    assert np.isclose(_f_norm2(np.array([3e-200, 4e-200])) / 5e-200, 1)
    assert _f_norm2(np.empty(0)) == 0
    assert _f_norm2(np.array([[3., 0.], [4., 5.]]), dim=1).tolist() == [5, 5]
    with pytest.raises(ValueError):
        _f_norm2(np.ones((2, 2)))


def test_pi_scaled_cardinal_values_are_exact():
    assert _f_sinpi([0, .5, 1, 1.5, 2, -1, 1e16]).tolist() == [0, 1, 0, -1, 0, 0, 0]
    assert _f_cospi([0, .5, 1, 1.5, 2, 1e16]).tolist() == [1, 0, -1, 0, 1, 1]
    assert np.allclose(_f_tanpi([0, .25, -.25, 1]), [0, 1, -1, 0])
    assert np.isclose(_f_sinpi(-1e-20) / (-np.pi * 1e-20), 1)
    assert np.isclose(_f_tanpi(-1e-20) / (-np.pi * 1e-20), 1)
    assert _f_epsilon(np.float32(1)) == np.finfo(np.float32).eps
    assert _f_epsilon(np.float64(1)) == np.finfo(np.float64).eps


def test_scipy_import_is_optional_and_not_triggered_by_labels():
    for source in ['print *, sqrt(4d0)', "print *, 'gamma(1) erfc_scaled(0)'"]:
        generated = basic_f2p().transpile('program demo\n' + source + '\nend program')
        assert 'import scipy' not in generated


def test_missing_scipy_has_actionable_message(monkeypatch):
    import sys
    generated = basic_f2p().transpile('program demo\nprint *, erfc_scaled(0d0)\nend program')
    assert 'sps.erfcx' in generated
    monkeypatch.setitem(sys.modules, 'scipy', None)
    with pytest.raises(ImportError, match='python -m pip install scipy'):
        exec(generated, {'__name__': 'dependency_test'})


def test_scaled_error_function_and_bessel_arrays():
    sps = pytest.importorskip('scipy.special')
    source = '''program demo
    use iso_fortran_env, only: real64
    real(real64) :: x(3), e(3), y(3)
    x = [0d0, 1d0, 30d0]
    e = erfc_scaled(x)
    y = bessel_y0([1d0,2d0,3d0]) + bessel_y1([1d0,2d0,3d0])
    end program'''
    # Inspect the expression mappings directly, then execute a function with
    # array outputs so the translation can be compared independently.
    translator = basic_f2p()
    generated = translator.transpile(source.replace('program demo', 'subroutine demo(e,y)').replace(
        'real(real64) :: x(3), e(3), y(3)',
        'real(real64) :: x(3)\nreal(real64), intent(out) :: e(3), y(3)').replace(
        'end program', 'end subroutine'))
    namespace = {'__name__': 'math_test'}
    exec(generated, namespace)
    e, y = namespace['demo'](None, None)
    assert np.allclose(e, sps.erfcx([0, 1, 30]))
    assert np.allclose(y, sps.y0([1,2,3]) + sps.y1([1,2,3]))
