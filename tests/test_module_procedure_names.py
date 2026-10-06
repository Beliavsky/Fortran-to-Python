from pathlib import Path
import subprocess
import sys

import pytest

from xf2p import basic_f2p


FIRST = '''module first
contains
integer function helper(i) result(r)
integer, intent(in) :: i
integer :: r
r=i+100
end function
end module
'''
SECOND = '''module second
contains
integer function helper(i)
integer, intent(in) :: i
helper=i+1
end function
integer function used(i)
integer, intent(in) :: i
used=helper(i)
end function
end module
'''


def execute(source, capsys):
    translated = basic_f2p().transpile(source)
    exec(translated, {'__name__': '__main__'})
    return capsys.readouterr().out.splitlines()


def test_original_module_collision(capsys):
    source = (Path(__file__).parent / 'cases/features/module_procedure_names.f90').read_text()
    assert execute(source, capsys) == ['3 102 3']


@pytest.mark.parametrize('reverse', [False, True])
def test_import_renames_and_module_local_calls(reverse, capsys):
    modules = SECOND+FIRST if reverse else FIRST+SECOND
    assert execute(modules+'''program main
use first, only: a=>helper
use second, only: b=>helper, used
print *, a(2), b(i=2), used(2)
end program
''', capsys) == ['102 3 3']


def test_use_without_only_with_rename(capsys):
    assert execute(FIRST+SECOND+'''program main
use first, a=>helper
use second
print *, a(2), helper(2), used(2)
end program
''', capsys) == ['102 3 3']


def test_procedure_local_use_overrides_host_mapping(capsys):
    second = SECOND.replace('used=helper(i)', 'use first, only: helper\nused=helper(i)')
    assert execute(FIRST+second+'''program main
use second, only: used
print *, used(2)
end program
''', capsys) == ['102']


def test_local_variable_and_block_shadow_import(capsys):
    assert execute(FIRST+SECOND+'''program main
use first, only: helper
print *, helper(2)
block
integer :: helper
helper=7
print *, helper
end block
print *, helper(3)
end program
''', capsys) == ['102', '7', '103']


def test_reexported_renamed_procedure(capsys):
    assert execute(FIRST+SECOND+'''module bridge
use first, only: selected=>helper
private
public :: selected
end module
program main
use bridge
print *, selected(2)
end program
''', capsys) == ['102']


def test_unreferenced_ambiguous_imports_are_allowed(capsys):
    assert execute(FIRST+SECOND+'''program main
use first
use second
print *, used(2)
end program
''', capsys) == ['3']


def test_referenced_ambiguous_import_is_diagnosed():
    with pytest.raises(ValueError, match='ambiguous USE-associated procedure'):
        basic_f2p().transpile(FIRST+SECOND+'''program main
use first
use second
print *, helper(2)
end program
''')


def test_strings_comments_and_keyword_labels_are_not_renamed(capsys):
    assert execute(FIRST+SECOND+'''program main
use first, only: helper
print *, 'helper', helper(i=2) ! helper remains in this comment
end program
''', capsys) == ['helper 102']


def test_private_helper_is_not_imported(capsys):
    second = SECOND.replace('module second', 'module second\nprivate\npublic :: used')
    assert execute(FIRST+second+'''program main
use first
use second
print *, helper(2), used(2)
end program
''', capsys) == ['102 3']


def test_type_bound_binding_retains_member_name(capsys):
    assert execute(FIRST+'''module second
type :: item
contains
procedure :: helper
end type
contains
integer function helper(this, i)
class(item), intent(in) :: this
integer, intent(in) :: i
helper=i+1
end function
end module
program main
use first, only: helper
use second, only: item
type(item) :: x
print *, helper(2), x%helper(2)
end program
''', capsys) == ['102 3']


def test_generic_wrappers_keep_distinct_specifics(capsys):
    first = FIRST.replace('contains', 'interface apply\nmodule procedure helper\nend interface\ncontains', 1)
    second = SECOND.replace('contains', 'interface apply\nmodule procedure helper\nend interface\ncontains', 1)
    assert execute(first+second+'''program main
use first, only: a=>apply
use second, only: b=>apply
print *, a(2), b(2)
end program
''', capsys) == ['102 3']


def test_modified_scalar_function_keeps_copyback(capsys):
    first = FIRST.replace('intent(in)', 'intent(inout)').replace('r=i+100', 'i=i+100\nr=i')
    assert execute(first+SECOND+'''program main
use first, only: a=>helper
use second, only: b=>helper
integer :: i, result
i=2
result=a(i)
print *, result, i, b(2)
end program
''', capsys) == ['102 102 3']


def test_separate_file_import_of_qualified_procedure_is_diagnosed(tmp_path):
    provider = tmp_path / 'provider.f90'
    consumer = tmp_path / 'consumer.f90'
    provider.write_text(FIRST+SECOND)
    consumer.write_text('''program main
use first, only: helper
print *, helper(2)
end program
''')
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'xf2p.py'),
                             str(provider), str(consumer)], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'qualified module names across separate Python files' in result.stdout


def test_subroutine_collision_keeps_scalar_copyback(capsys):
    assert execute(FIRST+'''module second
contains
subroutine helper(i)
integer, intent(inout) :: i
i=i+1
end subroutine
end module
program main
use first, only: a=>helper
use second, only: b=>helper
integer :: i
i=2
call b(i)
print *, a(2), i
end program
''', capsys) == ['102 3']


def test_internal_procedure_shadows_import(capsys):
    assert execute(FIRST+SECOND+'''module third
use first, only: helper
contains
integer function local(i)
integer, intent(in) :: i
local=helper(i)
contains
integer function helper(j)
integer, intent(in) :: j
helper=j+20
end function
end function
end module
program main
use third, only: local
print *, local(2)
end program
''', capsys) == ['22']
