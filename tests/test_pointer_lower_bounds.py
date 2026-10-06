from pathlib import Path

import numpy as np
import pytest

from fortran_py_runtime import (
    _f_pointer_associate, _f_array_lbound, _f_array_ubound,
    _f_set_array_bounds, _f_associated,
)
from xf2p import basic_f2p


def test_pointer_lower_bounds_fixture(capsys):
    source = (Path(__file__).parent / 'cases/features/pointer_lower_bounds.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == [
        '0 5 -3 2 -2 3', '200 200 True', '-1 1 200 40 60',
        '400 True', '-1 1 400', '-2 3 10 -1 400', '1 6 10',
        '0 2 200 400', '99', '0 2 -2 88 88',
        '-1 0 0 2 1 6', '77 True', '0 2 60 400 99', 'True 1 0 False',
    ]


def test_independent_pointer_descriptors():
    a = _f_set_array_bounds(np.arange(6), [-2])
    p = _f_pointer_associate(a, [0], rank=1)
    q = _f_pointer_associate(a, [-3], rank=1)
    assert (_f_array_lbound(a, 1), _f_array_lbound(p, 1), _f_array_lbound(q, 1)) == (-2, 0, -3)
    assert _f_associated(p, q)
    p[2] = 77
    assert a[2] == q[2] == 77
    inherited = _f_pointer_associate(p)
    assert _f_array_lbound(inherited, 1) == 0
    _f_set_array_bounds(inherited, [9])
    assert _f_array_lbound(p, 1) == 0


def test_strides_and_empty_bounds():
    a = np.arange(6)
    p = _f_pointer_associate(a[::-2], [-1])
    assert _f_array_lbound(p, 1) == -1
    assert _f_array_ubound(p, 1) == 1
    p[1] = 42
    assert a[3] == 42
    empty = _f_pointer_associate(a[:0], [-5])
    assert _f_array_lbound(empty, 1) == 1
    assert _f_array_ubound(empty, 1) == 0


@pytest.mark.parametrize('bounds', ['1:3', '1:2,1:3', ':', '0::2'])
def test_unsupported_bounds_are_diagnosed(bounds):
    source = f'''program main
integer, target :: a(6)
integer, pointer :: p(:)
p({bounds}) => a
end program
'''
    with pytest.raises(ValueError, match='pointer bounds remapping'):
        basic_f2p().transpile(source)


def test_lower_bound_count_must_match_rank():
    with pytest.raises(ValueError, match='match the pointer rank'):
        basic_f2p().transpile('''program main
integer, target :: a(6)
integer, pointer :: p(:)
p(0:,0:) => a
end program
''')


def test_target_rank_is_checked():
    with pytest.raises(ValueError, match='rank-changing'):
        _f_pointer_associate(np.arange(6), [0, 0], rank=2)


def test_initialized_pointer_inherits_whole_target_bounds(capsys):
    exec(basic_f2p().transpile('''program main
integer, target, save :: a(-1:1) = 5
integer, pointer :: p(:) => a
print *, lbound(p), ubound(p), p(-1)
end program
'''), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == '-1 1 5'


def test_initializer_does_not_use_bounds_of_a_shadowed_array():
    translator = basic_f2p()
    translator._decl_lbounds = {'x': ['-3']}
    translator._decl_ubounds = {'x': ['2']}
    result = translator._pointer_initializer_expr('x', set(), {'x': {'shape': None}})
    assert result == '_f_pointer_associate(x)'
    assert translator._decl_lbounds == {'x': ['-3']}
