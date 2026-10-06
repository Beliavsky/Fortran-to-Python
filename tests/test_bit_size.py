from pathlib import Path

import pytest

from fortran_py_runtime import _f_bit_size
from xf2p import basic_f2p


@pytest.mark.parametrize('kind', [1, 2, 4, 8, 16])
def test_bit_size_integer_kinds(kind):
    assert _f_bit_size(kind) == 8 * kind
    assert type(_f_bit_size(kind)) is int


@pytest.mark.parametrize('kind', [-1, 0, 3, 32])
def test_unsupported_integer_kind(kind):
    with pytest.raises(ValueError, match='unsupported Fortran integer kind for BIT_SIZE'):
        _f_bit_size(kind)


def test_bit_size_fixture(capsys):
    source = (Path(__file__).parent / 'cases/features/bit_size_inquiries.f90').read_text()
    generated = basic_f2p().transpile(source)
    exec(generated, {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == [
        '32 8 16 32 64', '16 16 32 32', '16 4 8', '8 64 128 128',
        '64 8 8', '64', '127 32767', '32 64 0', 'bit_size(0_int64)',
    ]


@pytest.mark.parametrize('expression', [
    'bit_size()', 'bit_size(1,2)', 'bit_size(x=1)',
    'bit_size(i=1,i=2)', 'bit_size(1.0)', 'bit_size(.true.)',
    'bit_size("word")', 'bit_size(unknown)',
])
def test_invalid_argument_is_diagnosed(expression):
    with pytest.raises(ValueError, match='BIT_SIZE'):
        basic_f2p().translate_expr(expression, set())


def test_generic_dispatch_uses_bit_size_result_kind(capsys):
    source = '''module m
interface choose
module procedure small, big
end interface
contains
integer function small(x)
integer(1), intent(in) :: x
small = 1
end function
integer function big(x)
integer(8), intent(in) :: x
big = 8
end function
end module
program main
use m
print *, choose(bit_size(0_1)), choose(bit_size(0_8))
end program
'''
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == '1 8'


def test_user_function_named_bit_size(capsys):
    exec(basic_f2p().transpile('''program main
print *, bit_size(3)
contains
integer function bit_size(i)
integer, intent(in) :: i
bit_size = i + 10
end function
end program
'''), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == '13'
