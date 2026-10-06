from pathlib import Path

import numpy as np
import pytest

from xf2p import basic_f2p


def test_fixture(capsys):
    source = (Path(__file__).parent / 'cases/features/component_scalar_expansion.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == [
        '3 3 3 -1.0 -1.0 7 7 7 7',
        '1.0 1.0 2.0 2.0 True True', 'abcabc',
        '4.0 4.0 5.0 5.0', '8.0 8.0', '-2 -2 -2 1 3', '11 11 11 True',
    ]


@pytest.mark.parametrize('declaration,rhs,expected', [
    ('integer', '2.9', 2), ('real', '3', 3.0),
    ('complex', '(4.0,5.0)', 4+5j), ('logical', '.true.', True),
    ('character(len=3)', "'abcdef'", 'abc'),
])
def test_storage_shape_dtype_and_identity_are_retained(declaration, rhs, expected):
    source = f'''module m
type :: box
{declaration} :: values(2,3)
end type
type(box) :: record
contains
subroutine update()
record%values = {rhs}
end subroutine
end module
'''
    namespace = {'__name__': 'test'}
    exec(basic_f2p().transpile(source), namespace)
    before = namespace['record'].values
    dtype = before.dtype
    namespace['update']()
    after = namespace['record'].values
    assert after is before
    assert after.shape == (2,3)
    assert after.dtype == dtype
    np.testing.assert_array_equal(after, np.full((2,3), expected))


def test_empty_component_array(capsys):
    exec(basic_f2p().transpile('''program main
type :: box
real :: values(0,2)
end type
type(box) :: record
record%values = -1
print *, size(record%values), shape(record%values)
end program
'''), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == '0 0 2'
