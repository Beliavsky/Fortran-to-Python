from pathlib import Path

import numpy as np
import pytest

from fortran_py_runtime import (
    _f_selected_int_kind, _f_selected_real_kind, _f_selected_logical_kind,
)
from xf2p import basic_f2p


@pytest.mark.parametrize('value, expected', [
    (-1, 1), (0, 1), (2, 1), (3, 2), (4, 2), (5, 4),
    (9, 4), (10, 8), (18, 8), (19, -1), (1000, -1),
])
def test_integer_selection_boundaries(value, expected):
    assert _f_selected_int_kind(value) == expected


@pytest.mark.parametrize('value, expected', [
    (-1, 1), (0, 1), (8, 1), (9, 2), (16, 2), (17, 4),
    (32, 4), (33, 8), (64, 8), (65, -1), (1000, -1),
])
def test_logical_selection_boundaries(value, expected):
    assert _f_selected_logical_kind(value) == expected


@pytest.mark.parametrize('arguments, expected', [
    ({}, 4), ({'p': -1, 'r': -1}, 4), ({'p': 6, 'r': 37}, 4),
    ({'p': 7}, 8), ({'r': 38}, 8), ({'p': 15, 'r': 307, 'radix': 2}, 8),
    ({'p': 16}, -1), ({'r': 308}, -2), ({'p': 16, 'r': 308}, -3),
    ({'radix': 10}, -5), ({'p': 1000, 'r': 10000, 'radix': 10}, -5),
    ({'radix': 2}, 4),
])
def test_real_selection_boundaries_and_failures(arguments, expected):
    assert _f_selected_real_kind(**arguments) == expected


@pytest.mark.parametrize('helper', [_f_selected_int_kind, _f_selected_real_kind,
                                    _f_selected_logical_kind])
@pytest.mark.parametrize('value', [1.5, True, [1], np.array([1]), '12'])
def test_selection_requires_scalar_integer(helper, value):
    with pytest.raises(TypeError, match='scalar INTEGER'):
        helper(value)


def test_numpy_integer_arguments():
    assert _f_selected_int_kind(np.array(12)) == 8
    assert _f_selected_real_kind(np.int32(12), np.int64(100)) == 8
    assert _f_selected_logical_kind(np.uint8(8)) == 1


@pytest.mark.parametrize('expression, expected', [
    ('selected_int_kind(r=12)', 8), ('SELECTED_LOGICAL_KIND(BITS=16)', 2),
    ('selected_real_kind(r=100,p=12)', 8), ('selected_real_kind(radix=2)', 4),
    ('selected_real_kind()', 4), ('selected_real_kind(6,radix=2,r=37)', 4),
    ('selected_int_kind(selected_real_kind(p=12))', 4),
])
def test_keyword_optional_and_nested_calls(expression, expected, capsys):
    source = f'program demo\nprint *, {expression}\nend program'
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert int(capsys.readouterr().out) == expected


@pytest.mark.parametrize('expression', [
    'selected_int_kind()', 'selected_int_kind(1,2)', 'selected_int_kind(p=12)',
    'selected_logical_kind()', 'selected_logical_kind(bits=8,bits=16)',
    'selected_real_kind(q=12)', 'selected_real_kind(p=6,6)',
    'selected_real_kind(6,p=12)', 'selected_real_kind(1,2,3,4)',
])
def test_invalid_argument_binding(expression):
    with pytest.raises(ValueError):
        basic_f2p().transpile(f'program demo\nprint *, {expression}\nend program')


def test_kind_parameter_declarations_and_model_inquiries(capsys):
    source = (Path(__file__).parent / 'cases/features/selected_kinds.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines()[0].split() == ['1', '2', '4', '8']


def test_strings_are_not_rewritten(capsys):
    source = "program demo\nprint *, 'selected_int_kind(12)'\nend program"
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == 'selected_int_kind(12)'
