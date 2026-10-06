from pathlib import Path

import numpy as np
import pytest

from fortran_py_runtime import _f_associated, _f_pointer_target
from xf2p import basic_f2p


def test_associated_targets_fixture(capsys):
    source = (Path(__file__).parent / 'cases/features/associated_targets.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == [
        'False False False', 'True True False', 'True True False',
        'False True', 'False True False', 'True', 'True False',
        'True False', '77', 'True', 'False False False',
        'True False', 'True False', '88',
    ]


def test_same_values_and_overlapping_storage_are_not_same_target():
    a = np.arange(8)
    assert _f_associated(a[1:5], a[1:5])
    assert not _f_associated(a[1:5], a[2:6])
    assert not _f_associated(a[::2], a[:4])
    assert not _f_associated(a, a.copy())
    assert not _f_associated(a, a.reshape(2, 4))
    assert _f_associated(a[::-1], a[::-1])
    assert not _f_associated(a[::-1], a)


def test_scalar_target_is_a_mutable_view():
    a = np.arange(6).reshape(2, 3)
    p = _f_pointer_target(a, (1, 2))
    assert p.shape == ()
    assert _f_associated(p, _f_pointer_target(a, (1, 2)))
    assert not _f_associated(p, _f_pointer_target(a, (0, 2)))
    p[...] = 42
    assert a[1, 2] == 42
    row = _f_pointer_target(a, (1, slice(None)))
    assert _f_associated(row, a[1, :])


def test_null_and_empty_targets():
    a = np.empty(0)
    assert _f_associated(a)
    assert not _f_associated(a, a)
    assert not _f_associated(None)
    assert not _f_associated(None, a)
    assert not _f_associated(a, None)


def test_singleton_stride_is_irrelevant():
    a = np.arange(10)
    assert _f_associated(a[:1], a[:1:2])


def test_derived_type_identity():
    class Box:
        pass
    a, b = Box(), Box()
    assert _f_associated(a, a)
    assert not _f_associated(a, b)


def test_unboxed_scalar_identity_is_not_guessed():
    with pytest.raises(ValueError, match='preserved storage'):
        _f_associated(1, 1)


@pytest.mark.parametrize('expression', [
    'associated()', 'associated(p, a, b)', 'associated(p, pointer=q)',
    'associated(target=a)', 'associated(other=p)',
])
def test_bad_argument_lists_rejected(expression):
    with pytest.raises(ValueError, match='ASSOCIATED'):
        basic_f2p().translate_expr(expression, {'p', 'q', 'a', 'b'})


def test_scalar_pointer_component(capsys):
    exec(basic_f2p().transpile('''program main
type :: box
integer, pointer :: p => null()
end type
type(box) :: b
integer, target :: x, y
x = 1
y = 1
b%p => x
print *, associated(b%p, x), associated(b%p, y)
end program
'''), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == 'True False'


def test_initialized_scalar_element_pointer(capsys):
    exec(basic_f2p().transpile('''program main
integer, target, save :: a(3) = 5
integer, pointer :: p => a(2)
print *, associated(p, a(2)), associated(p, a(1))
p = 9
print *, a(2)
end program
'''), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == ['True False', '9']
