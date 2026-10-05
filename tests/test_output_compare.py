import pytest

from fortran_output_compare import compare_outputs, validate_tolerances
import xf2p_batch
from xf2p import _report_run_diff


def test_rounding_and_fortran_exponents():
    assert compare_outputs('sqrt(x) = 0.83666002653407556',
                           'sqrt(x) = 0.8366600265340756')['status'] == 'match'
    assert compare_outputs('v 1D0 -2d-1', 'v 1.0000000001 -0.2')['status'] == 'match'
    assert xf2p_batch.compare is compare_outputs


def test_integers_and_labels_are_exact():
    assert compare_outputs('19', '18', 1, 1)['status'] == 'mismatch'
    assert compare_outputs('9007199254740993', '9007199254740992', 1, 1)['status'] == 'mismatch'
    assert compare_outputs('a 1.0', 'b 1.0')['status'] == 'mismatch'


@pytest.mark.parametrize('reference, actual', [
    ('T', 'True'), ('F', 'False'),
    ('T F T\nF', 'True False\nTrue False'),
    ('1 F F\n1 F T\n3', '1 False False\n1 False True\n3'),
])
def test_logical_spellings(reference, actual):
    assert compare_outputs(reference, actual)['status'] == 'match'
    assert compare_outputs(actual, reference)['status'] == 'match'
    assert compare_outputs(reference, actual, exact=True)['status'] == 'mismatch'


@pytest.mark.parametrize('reference, actual', [
    ('T', 'False'), ('F', 'True'), ('True', 'False'),
    ('T', '1'), ('F', '0'), ('flag=T', 'flag=True'),
    ('"T"', '"True"'), ('TRUE', 'True'), ('t', 'True'),
])
def test_logical_mismatches_and_nonstandalone_text(reference, actual):
    assert compare_outputs(reference, actual, rtol=1, atol=1)['status'] == 'mismatch'


def test_logical_first_mismatch_diagnostics(capsys):
    assert not _report_run_diff('T\nF\n', 'True\nTrue\n')
    output = capsys.readouterr().out
    assert 'first mismatch line: 2' in output
    assert 'fortran: F' in output
    assert 'python : True' in output


def test_tolerances_and_exact_mode():
    assert compare_outputs('v 1.0', 'v 1.001')['status'] == 'mismatch'
    assert compare_outputs('v 1.0', 'v 1.001', rtol=.01)['status'] == 'match'
    assert compare_outputs('v 0.0', 'v 1e-12', rtol=0, atol=1e-11)['status'] == 'match'
    assert compare_outputs('v 0.0', 'v 1e-12', rtol=0, atol=0)['status'] == 'mismatch'
    assert compare_outputs('  v  1.0\r\n', 'v 1.0\n', exact=True)['status'] == 'match'
    assert compare_outputs('v 1.0', 'v 1.00', exact=True)['status'] == 'mismatch'


def test_wrapping_and_missing_output():
    assert compare_outputs('1 2\n3', '1\n2 3')['status'] == 'match'
    assert compare_outputs('1 2\n3', '1\n2 3', exact=True)['status'] == 'mismatch'
    result = compare_outputs('header\n1 2', 'header\n1')
    assert result['status'] == 'mismatch'
    assert result['reference_line'] == 2
    assert 'Token counts differ' in result['detail']
    assert compare_outputs('', '')['status'] == 'match'
    assert compare_outputs('', '1')['status'] == 'mismatch'


def test_first_genuine_mismatch_skips_close_values(capsys):
    assert not _report_run_diff('  close 1D0\r\n bad 2\r\n', 'close 1.0000000001\nbad 3\n')
    output = capsys.readouterr().out
    assert 'first mismatch line: 2' in output
    assert 'fortran: bad 2' in output
    assert 'python : bad 3' in output
    assert 'fortran: close' not in output


def test_nonfinite_and_signed_zero():
    assert compare_outputs('NaN Infinity -Infinity -0.0', 'nan inf -inf 0.0')['status'] == 'match'
    assert compare_outputs('inf', '-inf')['status'] == 'mismatch'
    assert compare_outputs('nan', '1.0')['status'] == 'mismatch'


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf')])
def test_invalid_tolerances(value):
    with pytest.raises(ValueError, match='finite and nonnegative'):
        validate_tolerances(value, 0)
    with pytest.raises(ValueError):
        validate_tolerances(0, value)


@pytest.mark.parametrize('reference,actual', [
    ('(1.0000000000000000,2.0000000000000000)', '(1.0,2.0)'),
    ('( 1D0,\n -2d-1 )', '(1.0,-0.2)'),
    ('(1,2)', '(1.0000000001,2.0)'),
    ('(nan,Infinity) (-Infinity,-0.0)', '(NaN,inf) (-inf,0.0)'),
    ('z (1.0, 2.0) (3.0, 4.0) done', 'z (1,2)\n(3,4) done'),
])
def test_complex_components_compare_numerically(reference, actual):
    assert compare_outputs(reference, actual)['status'] == 'match'
    assert compare_outputs(actual, reference)['status'] == 'match'
    assert compare_outputs(reference, actual, exact=True)['status'] == 'mismatch'


@pytest.mark.parametrize('reference,actual', [
    ('(1.0,2.0)', '(1.01,2.0)'), ('(1.0,2.0)', '(1.0,2.01)'),
    ('(inf,2)', '(-inf,2)'), ('(nan,2)', '(1,2)'),
    ('(1,2)', '1 2'), ('(1,2)', '(1+2j)'),
    ('z=(1.0,2.0)', 'z=(1,2)'), ('"(1.0,2.0)"', '"(1,2)"'),
    ('(1,2,3)', '(1.0,2.0,3.0)'), ('(1,word)', '(1.0,word)'),
    ('(1,2)(3,4)', '(1.0,2.0)(3.0,4.0)'),
])
def test_complex_mismatches_and_nonstandalone_text(reference, actual):
    assert compare_outputs(reference, actual)['status'] == 'mismatch'


def test_complex_tolerances_are_component_wise():
    assert compare_outputs('(1e20,0)', '(1e20,1e-4)')['status'] == 'mismatch'
    assert compare_outputs('(1,0)', '(1,1e-12)', atol=1e-11)['status'] == 'match'
    assert compare_outputs('(1,0)', '(1,1e-12)', atol=0)['status'] == 'mismatch'
    assert compare_outputs('(1,2)', '(1.001,2)', rtol=.01)['status'] == 'match'
    assert compare_outputs('19 (1,2)', '18 (1,2)', rtol=1, atol=1)['status'] == 'mismatch'


def test_complex_first_mismatch_preserves_line_information():
    result = compare_outputs('header\n(1D0, 2D0)\n(3, 4)',
                             'header\n(1,2)\n(3,5)')
    assert result['status'] == 'mismatch'
    assert result['token'] == 3
    assert result['reference_line'] == result['actual_line'] == 3
    assert result['reference_text'] == '(3, 4)'
    assert '(3,5)' in result['detail']
