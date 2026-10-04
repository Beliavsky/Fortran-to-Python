import ast
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from xf2p import basic_f2p


MODULE = '''module state
integer :: count = 0
contains
subroutine tick()
count = count + 1
end subroutine
end module
'''


def execute(source, capsys, repetitions=1):
    generated = basic_f2p().transpile(source)
    namespace = {'__name__': 'use_test'}
    exec(generated, namespace)
    for _ in range(repetitions):
        namespace['main']()
    return capsys.readouterr().out.split(), generated


def test_main_and_module_procedure_share_scalars_and_array_metadata(capsys):
    source = (Path(__file__).parent / 'cases/features/use_module_state.f90').read_text()
    output, generated = execute(source, capsys)
    assert output == ['11', '3.0', '3.0', 'ok', '16', '99', '16']
    main = next(node for node in ast.parse(generated).body
                if isinstance(node, ast.FunctionDef) and node.name == 'main')
    assert any(isinstance(node, ast.Global) and 'count' in node.names for node in main.body)
    assert not any(isinstance(node, ast.Nonlocal) and 'count' in node.names for node in ast.walk(main))


def test_use_only_does_not_capture_unimported_variable(capsys):
    source = MODULE + '''program p
use state, only: tick
integer :: count
count = 99
call tick()
print *, count
end program'''
    output, generated = execute(source, capsys)
    assert output == ['99']
    assert 'global count' not in generated.split('def main()', 1)[1]


def test_shared_storage_is_not_reinitialized_on_main_entry(capsys):
    source = MODULE + '''program p
use state, only: count, tick
call tick()
print *, count
end program'''
    assert execute(source, capsys, repetitions=2)[0] == ['1', '2']


def test_procedure_own_use_and_transitive_reexport(capsys):
    source = MODULE + '''module bridge
use state, only: count, tick
contains
subroutine bump()
use state, only: count
count = count + 10
end subroutine
end module
program p
use bridge
count = 5
call bump()
call tick()
print *, count
end program'''
    assert execute(source, capsys)[0] == ['16']


def test_private_variable_does_not_override_main_local(capsys):
    source = MODULE.replace('integer :: count = 0', 'private\npublic :: tick\ninteger :: count = 0')
    source += '''program p
use state
integer :: count
count = 99
call tick()
print *, count
end program'''
    assert execute(source, capsys)[0] == ['99']


def test_reexport_obeys_importing_module_private_default(capsys):
    source = MODULE.replace('integer :: count = 0', 'integer, public :: count = 0')
    source += '''module bridge
use state
private
public :: bump
contains
subroutine bump()
count = count + 1
end subroutine
end module
program p
use bridge
integer :: count
count = 99
call bump()
print *, count
end program'''
    assert execute(source, capsys)[0] == ['99']


def test_internal_procedure_local_shadows_use_associated_host(capsys):
    source = MODULE + '''program p
use state
count = 5
call shadow()
print *, count
contains
subroutine shadow()
integer :: count
count = 99
print *, count
end subroutine
end program'''
    assert execute(source, capsys)[0] == ['99', '5']


def test_renamed_module_variable_is_explicitly_rejected():
    with pytest.raises(ValueError, match='renamed USE-associated'):
        basic_f2p().transpile(MODULE + 'program p\nuse state, only: local => count\nlocal=5\nend program')


def test_duplicate_module_storage_names_are_explicitly_rejected():
    with pytest.raises(ValueError, match='separate module namespaces'):
        basic_f2p().transpile(MODULE + 'module other\ninteger :: count\nend module\nprogram p\nprint *, 1\nend program')


@pytest.mark.parametrize('separate, renamed', [(False, False), (True, False), (True, True)])
def test_single_input_shares_storage_and_separate_files_reject_copy(tmp_path, separate, renamed):
    provider = tmp_path / 'state.f90'
    provider.write_text(MODULE)
    main = tmp_path / 'main.f90'
    main.write_text('program p\nuse state\ncount=10\ncall tick()\nprint *, count\nend program')
    if renamed:
        main.write_text('program p\nuse state, only: local => count, tick\nlocal=10\ncall tick()\nprint *, local\nend program')
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'xf2p.py'),
               str(provider), str(main)]
    if not separate:
        combined = tmp_path / 'combined.f90'
        combined.write_text(provider.read_text() + main.read_text())
        command = command[:2] + [str(combined)]
        compiler = shutil.which('gfortran')
        if compiler is None:
            pytest.skip('gfortran required')
        command += ['--run-diff', '--compiler', f'"{compiler}" -O0']
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=90)
    if separate:
        assert result.returncode == 1, result.stdout + result.stderr
        assert 'mutable USE-associated variables across separate Python files' in result.stdout
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'Run diff: MATCH' in result.stdout
