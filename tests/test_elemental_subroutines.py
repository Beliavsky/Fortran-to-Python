from pathlib import Path

import numpy as np
import pytest

from fortran_py_runtime import _f_elemental_subroutine
from xf2p import basic_f2p


def test_input_only_calls_are_once_per_element_and_in_fortran_order():
    seen = []
    a = np.array([[1, 3], [2, 4]])
    assert _f_elemental_subroutine(lambda x, s: seen.append((int(x), s)), [a, 9], [], []) is None
    assert seen == [(1, 9), (2, 9), (3, 9), (4, 9)]
    _f_elemental_subroutine(lambda x: pytest.fail('empty call'), [np.empty((0, 2))], [], [])


def test_outputs_preserve_views_and_multiple_return_values():
    a = np.arange(6)
    view = a[::2]
    out = np.empty(3, dtype=int)
    seen = []

    def update(x, y, scale):
        assert y is None
        seen.append(int(x))
        return x + scale, x * scale

    returned = _f_elemental_subroutine(update, [view, out, 2], [0, 1], [int, int], [1])
    assert returned[0] is view and returned[1] is out
    assert seen == [0, 2, 4]
    assert a.tolist() == [2, 1, 4, 3, 6, 5]
    assert out.tolist() == [0, 4, 8]


def test_output_only_and_empty_arrays():
    out = np.empty((2, 2), dtype=int)
    assert _f_elemental_subroutine(lambda x: 7, [out], [0], [int], [0]) is out
    assert out.tolist() == [[7, 7], [7, 7]]
    empty = np.empty((0, 2), dtype=int)
    assert _f_elemental_subroutine(lambda x: pytest.fail('empty call'), [empty], [0], [int], [0]) is empty


def test_nonconformable_arguments_and_scalar_output_are_rejected():
    with pytest.raises(ValueError, match='conformable'):
        _f_elemental_subroutine(lambda a, b: None, [np.zeros((2, 1)), np.zeros(2)], [], [])
    with pytest.raises(ValueError, match='outputs must be arrays'):
        _f_elemental_subroutine(lambda a, b: 7, [np.zeros(2), 0], [1], [int], [1])


@pytest.mark.parametrize('prefix', ['impure elemental', 'elemental impure', 'pure elemental'])
def test_qualified_subroutine_headers_and_keyword_outputs(prefix, capsys):
    source = f'''program test
integer :: x(2), y(2)
x = [2,4]
call doubled(y=y, x=x)
print *, y
contains
{prefix} subroutine doubled(x, y)
integer, intent (in) :: x
integer, intent (out) :: y
y = x * 2
end subroutine
end program
'''
    translated = basic_f2p().transpile(source)
    exec(translated, {'__name__': '__main__'})
    assert capsys.readouterr().out.split() == ['4', '8']


def test_fixture_input_only_scalar_output_and_strided_actuals(capsys):
    source = (Path(__file__).parent / 'cases/features/impure_elemental_subroutines.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ['0.0', '0.0', '1.0', '2.0', '4']
    assert lines[1].split() == ['0.0', '5']
    assert [int(line.split()[0]) for line in lines[2:10]] == [2,4,6,8,10,12,14,16]
    assert lines[10].split() == ['7', '7', '7']
    assert lines[11].split() == ['0.0', '-2.0', '0.0', '4.0', '7']
