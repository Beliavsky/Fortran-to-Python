from pathlib import Path
import subprocess

import numpy as np
import pytest

import fortran_py_runtime as runtime
from xf2p import basic_f2p


def execute(source):
    namespace = {'__name__': '__main__'}
    exec(basic_f2p().transpile(source), namespace)


def fake_command(monkeypatch, code=0):
    calls = []
    def run(command, **options):
        calls.append((command,options))
        return subprocess.CompletedProcess(command,code)
    monkeypatch.setattr(runtime.subprocess,'run',run)
    return calls


@pytest.mark.parametrize('code', [0,3,7,127])
def test_completed_shell_status_is_not_launch_failure(monkeypatch, code):
    calls = fake_command(monkeypatch,code)
    assert runtime._f_execute_command_line('  exit 7   ') == (code,0,None)
    assert calls == [('  exit 7', {'shell':True,'check':False})]


@pytest.mark.parametrize('error', [OSError('shell unavailable'), ValueError('embedded null')])
def test_launch_failure_reports_status_or_raises(monkeypatch, error):
    def run(*args, **kwargs):
        raise error
    monkeypatch.setattr(runtime.subprocess,'run',run)
    assert runtime._f_execute_command_line('anything',has_cmdstat=True) == (None,1,str(error))
    with pytest.raises(RuntimeError, match='could not launch shell'):
        runtime._f_execute_command_line('anything')


@pytest.mark.parametrize('wait', [False,np.bool_(False),np.array(False)])
def test_dynamic_asynchronous_execution_is_rejected_without_launch(monkeypatch, wait):
    calls = fake_command(monkeypatch)
    with pytest.raises(NotImplementedError, match='asynchronous'):
        runtime._f_execute_command_line('anything',wait,has_cmdstat=True)
    assert not calls


@pytest.mark.parametrize('command,wait', [(1,True),(['echo test'],True),
    ('echo test',1),('echo test',[True]),('echo test','true')])
def test_scalar_argument_types(monkeypatch, command, wait):
    calls = fake_command(monkeypatch)
    with pytest.raises(TypeError, match='requires scalar'):
        runtime._f_execute_command_line(command,wait)
    assert not calls


@pytest.mark.parametrize('call', [
    "call execute_command_line('test',.true.,result,status,message)",
    "call execute_command_line(command='test',cmdmsg=message,cmdstat=status,exitstat=result)",
])
def test_success_sets_status_and_leaves_message_unchanged(monkeypatch, capsys, call):
    fake_command(monkeypatch,7)
    execute(f'''program demo
integer :: result,status
character(len=8) :: message
message = 'keep'
{call}
print *, result,status,trim(message)
end program''')
    assert capsys.readouterr().out.strip() == '7 0 keep'


@pytest.mark.parametrize('size,expected', [(5,'shell'),(24,'shell unavailable       ')])
def test_error_preserves_exitstat_and_assigns_fixed_length_message(monkeypatch, capsys, size, expected):
    def run(*args, **kwargs):
        raise OSError('shell unavailable')
    monkeypatch.setattr(runtime.subprocess,'run',run)
    execute(f'''program demo
integer :: result = 99,status = 88
character(len={size}) :: message
call execute_command_line('test',exitstat=result,cmdstat=status,cmdmsg=message)
print *, result,status
print *, message
end program''')
    assert capsys.readouterr().out.splitlines() == ['99 1',expected]


def test_message_without_cmdstat_does_not_suppress_error(monkeypatch):
    def run(*args, **kwargs):
        raise OSError('missing shell')
    monkeypatch.setattr(runtime.subprocess,'run',run)
    with pytest.raises(RuntimeError,match='could not launch shell'):
        execute('''program demo
character(len=20) :: message
call execute_command_line('test',cmdmsg=message)
end program''')


def test_error_outputs_to_components_and_array_elements(monkeypatch, capsys):
    def run(*args, **kwargs):
        raise OSError('failed')
    monkeypatch.setattr(runtime.subprocess,'run',run)
    execute('''program demo
type record
integer :: status
character(len=8) :: message
end type
type(record) :: info
integer :: codes(2)
codes = 99
call execute_command_line('test',exitstat=codes(1),cmdstat=info%status,cmdmsg=info%message)
print *, codes,info%status
print *, info%message
end program''')
    assert capsys.readouterr().out.splitlines() == ['99 99 1','failed  ']


@pytest.mark.parametrize('call', [
    'call execute_command_line()',
    "call execute_command_line('test',wait=.false.)",
    "call execute_command_line('test',wait=(.false.))",
    "call execute_command_line('test',cmdstat=1)",
    "call execute_command_line('test',cmdstat=codes)",
    "call execute_command_line('test',cmdstat=codes(:))",
    "call execute_command_line('test',cmdstat=message)",
    "call execute_command_line('test',cmdmsg=codes(1))",
    "call execute_command_line('test',cmdmsg=message(1:2))",
    "call execute_command_line('test',cmdstat=status,cmdstat=status)",
    "call execute_command_line('test',foo=1)",
    "call execute_command_line(command='test',.true.)",
])
def test_bad_bindings_and_unsupported_forms_are_diagnosed(call):
    source = f'''program demo
integer :: status,codes(2)
character(len=8) :: message
{call}
end program'''
    with pytest.raises(ValueError):
        basic_f2p().transpile(source)


def test_dynamic_false_wait_in_translation(monkeypatch):
    calls = fake_command(monkeypatch)
    with pytest.raises(NotImplementedError,match='asynchronous'):
        execute('''program demo
logical :: waiting
waiting = .false.
call execute_command_line('test',wait=waiting)
end program''')
    assert not calls


def test_native_status_fixture_with_mocked_commands(monkeypatch, capsys):
    def run(command, **options):
        if command == 'echo command_ok':
            print('command_ok')
            return subprocess.CompletedProcess(command,0)
        return subprocess.CompletedProcess(command,int(command.split()[1]))
    monkeypatch.setattr(runtime.subprocess,'run',run)
    source = (Path(__file__).parent / 'cases/features/execute_command_status.f90').read_text()
    execute(source)
    assert capsys.readouterr().out.splitlines() == [
        'before','command_ok','after','0 0 unchanged','7 0','3 0','5 0',
    ]
