from pathlib import Path

import numpy as np
import pytest

from xf2p import basic_f2p


def execute(source):
    translated = basic_f2p().transpile(source)
    namespace = {'__name__': '__main__'}
    exec(translated, namespace)
    return namespace, translated


def test_real_literals_variables_expressions_and_ranks(capsys):
    source = (Path(__file__).parent / 'cases/features/generic_real_kinds.f90').read_text()
    execute(source)
    assert capsys.readouterr().out.splitlines() == [
        'scalar32', 'scalar64', 'scalar64', 'scalar32', 'scalar64',
        'scalar32', 'scalar64', 'scalar64', 'vector32', 'vector64',
        'matrix64', 'scalar64', 'vector64', 'scalar64',
    ]


def module_source(type_name='real'):
    return f'''module kinds
interface choose
module procedure small, large
end interface
contains
integer function small(x)
{type_name}(kind=4), intent(in) :: x
small=4
end function
integer function large(x)
integer, parameter :: dp=8
{type_name}(kind=dp), intent(in) :: x
large=8
end function
end module
'''


@pytest.mark.parametrize('type_name,actual', [
    ('real', '1.0d0'), ('integer', '1_8'), ('complex', 'z'),
])
def test_numeric_kinds_and_function_generics(type_name, actual, capsys):
    declarations = 'complex(kind=8) :: z\nz=(1.0d0,2.0d0)' if type_name == 'complex' else ''
    execute(module_source(type_name) + f'''program main
use kinds
{declarations}
print *, choose({actual})
end program
''')
    assert capsys.readouterr().out.splitlines() == ['8']


def test_no_matching_specific(capsys):
    with pytest.raises(TypeError, match='no matching specific'):
        execute(module_source() + '''program main
use kinds
print *, choose(1.0_16)
end program
''')


def test_keyword_binding_reorders_kind_hints(capsys):
    execute('''module kinds
interface choose
module procedure first, second
end interface
contains
integer function first(x,y)
real(4), intent(in) :: x
real(8), intent(in) :: y
first=48
end function
integer function second(x,y)
real(8), intent(in) :: x
real(4), intent(in) :: y
second=84
end function
end module
program main
use kinds
print *, choose(y=1.0d0,x=1.0), choose(1.0d0,y=1.0)
end program
''')
    assert capsys.readouterr().out.splitlines() == ['48 84']


def test_untagged_python_calls_use_numpy_kind(capsys):
    namespace, _ = execute(module_source() + 'program main\nend program\n')
    assert namespace['choose'](np.float32(1)) == 4
    assert namespace['choose'](np.float64(1)) == 8


def test_unknown_kind_is_not_silently_guessed():
    namespace, _ = execute(module_source() + 'program main\nend program\n')
    with pytest.raises(TypeError, match='cannot determine Fortran kind'):
        namespace['choose'](1.0, _xf2p_kind_hints=[-1])


def test_empty_array_uses_declared_kind_and_element_type(capsys):
    execute('''module kinds
interface choose
module procedure integers, small, large
end interface
contains
integer function integers(x)
integer, intent(in) :: x(:)
integers=0
end function
integer function small(x)
real(4), intent(in) :: x(:)
small=4
end function
integer function large(x)
real(8), intent(in) :: x(:)
large=8
end function
end module
program main
use kinds
real(4) :: a(0)
real(8) :: b(0)
integer :: c(0)
print *, choose(a), choose(b), choose(c)
end program
''')
    assert capsys.readouterr().out.splitlines() == ['4 8 0']
