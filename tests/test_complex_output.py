import math
from pathlib import Path

import numpy as np
import pytest

from fortran_output_compare import COMPLEX, compare_outputs
from xf2p import basic_f2p


def format_scalar(value):
    namespace = {'__name__': 'output_test'}
    exec(basic_f2p().transpile('program demo\nprint *, 1\nend program'), namespace)
    return namespace['_xf2p_io_scalar'](value)


@pytest.mark.parametrize('value', [
    complex(1.2345678901234567, -2.345678901234567),
    complex(1e-200, -1e-200), complex(1e200, -1e200),
    complex(-0.0, 0.0), np.complex64(1.25 - 2.5j),
    np.complex128(1.2345678901234567 + 2.345678901234567j),
    np.array(complex(1e-200, -1e200)),
])
def test_complex_output_round_trips_components(value):
    actual = format_scalar(value)
    match = COMPLEX.fullmatch(actual)
    assert match is not None
    components = [float(component) for component in match.groups()]
    expected = [float(np.real(value)), float(np.imag(value))]
    assert components == expected
    for a, b in zip(components, expected):
        if b == 0:
            assert math.copysign(1, a) == math.copysign(1, b)


def test_complex_nonfinite_output():
    actual = format_scalar(complex(float('inf'), float('nan')))
    assert actual == '(inf,nan)'
    assert compare_outputs('(Infinity,NaN)', actual)['status'] == 'match'


def test_real_output_is_unchanged():
    for value in [1e-200, 1e200, 1.2345678901234567, np.float64(2.5)]:
        assert format_scalar(value) is value


def test_complex_array_output_preserves_fortran_order(capsys):
    source = (Path(__file__).parent / 'cases/features/complex_output.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    output = capsys.readouterr().out
    assert '(1e-200,-1e-200)' in output
    assert '(1e+200,-1e+200)' in output
    assert output.index('(1e-200,-1e-200)') < output.index('(1e+200,-1e+200)')
    assert '1.2345678901234567' in output
    assert output.startswith('scalar (1.0,2.0) (1.0,-2.0) ')


def test_complex_output_separation_and_character_concatenation(capsys):
    namespace = {'__name__': 'output_test'}
    exec(basic_f2p().transpile('program demo\nprint *, 1\nend program'), namespace)
    z = complex(1, 2)
    namespace['_xf2p_print_star']('z', z, z)
    assert capsys.readouterr().out == 'z (1.0,2.0) (1.0,2.0)\n'
    assert namespace['_xf2p_star_text']('z', z, z) == 'z (1.0,2.0) (1.0,2.0)'
    namespace['_xf2p_print_star']('left', 'right')
    assert capsys.readouterr().out == 'leftright\n'
    assert namespace['_xf2p_star_text']('left', 'right') == 'leftright'
