import subprocess
import sys

import pytest

import xf2p
from xf2p import basic_f2p


@pytest.mark.parametrize('operation, symbol, description', [
    ('operator', '+', 'operator overloading'),
    ('OPERATOR', '.cross.', 'operator overloading'),
    ('operator', '.eq.', 'operator overloading'),
    ('assignment', '=', 'defined assignment'),
])
def test_generic_interface_reports_operation_and_procedures(operation, symbol, description):
    source = f'''module m
interface {operation} ( {symbol} )
module procedure &
 & first, second
end interface
end module
'''
    with pytest.raises(ValueError) as caught:
        basic_f2p().transpile(source)
    assert description in str(caught.value)
    assert f'{operation.upper()}({symbol})' in str(caught.value)
    assert 'first, second' in str(caught.value)


def test_explicit_procedure_interface_reports_procedure():
    source = '''module m
interface operator(.cross.)
function cross(a,b) result(c)
integer :: a,b,c
end function
end interface
end module
'''
    with pytest.raises(ValueError, match=r'procedure\(s\): cross'):
        basic_f2p().transpile(source)


@pytest.mark.parametrize('operation', ['operator(+)', 'assignment(=)'])
def test_type_bound_generic_reports_unsupported_operation(operation):
    source = f'''module m
type t
contains
procedure :: impl
generic, public :: {operation} => impl
end type
end module
'''
    with pytest.raises(ValueError) as caught:
        basic_f2p().transpile(source)
    assert operation.upper() in str(caught.value)
    assert 'impl' in str(caught.value)


def test_intrinsic_operations_and_operator_text_are_unaffected(capsys):
    source = '''program test
integer :: x
! interface operator(+)
x = 2 + 3 * 4
print *, x, x == 14
print *, 'interface assignment(=)'
end program
'''
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == ['14 True', 'interface assignment(=)']


@pytest.mark.parametrize('operation, message, procedure, implementation', [
    ('operator(+)', 'operator overloading', 'add_vector2',
     'function add_vector2(a,b) result(c)\ntype(t), intent(in) :: a,b\n'
     'type(t) :: c\nc%v = a%v + b%v\nend function'),
    ('assignment(=)', 'defined assignment', 'assign_integer_to_box',
     'subroutine assign_integer_to_box(lhs,rhs)\ntype(t), intent(out) :: lhs\n'
     'integer, intent(in) :: rhs\nlhs%v = rhs\nend subroutine'),
])
def test_cli_reports_failure_without_creating_python(tmp_path, operation, message, procedure, implementation):
    source = tmp_path / 'defined_operation.f90'
    source.write_text(f'module m\ntype t\ninteger :: v\nend type\n'
                      f'interface {operation}\nmodule procedure {procedure}\nend interface\n'
                      f'contains\n{implementation}\nend module\nprogram p\nuse m\nend program\n')
    output = tmp_path / 'translated.py'
    result = subprocess.run([sys.executable, xf2p.__file__, str(source), '--out', str(output)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'Transpile: FAIL' in result.stdout
    assert message in result.stdout and procedure in result.stdout
    assert 'Traceback' not in result.stderr
    assert not output.exists()


def test_named_generic_interface_still_translates(capsys):
    source = '''module m
interface twice
module procedure double_integer
end interface
contains
integer function double_integer(x)
integer, intent(in) :: x
double_integer = x * 2
end function
end module
program test
use m
print *, twice(3)
end program
'''
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == '6'
