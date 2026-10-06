from pathlib import Path

import pytest

from xf2p import basic_f2p, infer_function_result_ftype, parse_decl


def execute(source):
    translated = basic_f2p().transpile(source)
    exec(translated, {'__name__': '__main__'})
    return translated


def test_original_double_declarations(capsys):
    source = (Path(__file__).parent / 'cases/features/double_types.f90').read_text()
    execute(source)
    assert capsys.readouterr().out.splitlines() == ['4 8', '4 8']


@pytest.mark.parametrize('declaration,family', [
    ('double precision :: y', 'real'), ('DOUBLE   PRECISION :: y', 'real'),
    ('double complex :: y', 'complex'), ('double complex, intent(in) :: y', 'complex'),
    ('double precision, dimension(2) :: y', 'real'),
])
def test_declarations_normalize_to_kind_eight(declaration, family):
    ftype, attrs, rest = parse_decl(declaration)
    assert ftype == family
    assert attrs.startswith('(kind=8)')
    assert rest == 'y'


@pytest.mark.parametrize('prefix,family', [
    ('double precision', 'real'), ('pure double precision', 'real'),
    ('double complex', 'complex'), ('elemental double complex', 'complex'),
])
def test_typed_function_headers(prefix, family):
    assert infer_function_result_ftype(prefix + ' function f(x)') == family


def test_arrays_parameters_components_and_typed_results(capsys):
    execute('''module double_checks
implicit none
double precision, parameter :: factor=2.0d0
type box
double precision :: r
double complex :: z
end type
contains
pure double precision function scale(x)
double precision, intent(in) :: x
scale=factor*x
end function
double complex function make_value()
make_value=(1.0d0,2.0d0)
end function
subroutine report(x,z)
double precision, intent(in) :: x(:)
double complex, intent(in) :: z(:)
print *, kind(x), kind(z)
end subroutine
end module
program main
use double_checks
implicit none
double precision :: x(2)=[1.0d0,2.0d0]
double complex :: z(2)=[(1.0d0,2.0d0),(3.0d0,4.0d0)]
type(box) :: b
print *, kind(factor), kind(x(1)), kind(z(1)), kind(b%r), kind(b%z)
print *, kind(scale(2.0d0)), kind(make_value())
print *, int(scale(3.0d0)), int(real(make_value())), int(aimag(make_value()))
call report(x,z)
end program
''')
    assert capsys.readouterr().out.splitlines() == ['8 8 8 8 8', '8 8', '6 1 2', '8 8']
