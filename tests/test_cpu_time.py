from pathlib import Path

import pytest

import fortran_py_runtime as runtime
from xf2p import basic_f2p


def test_cpu_time_uses_process_clock(monkeypatch):
    calls = []
    def clock():
        calls.append(1)
        return 12.5
    monkeypatch.setattr(runtime.time, 'process_time', clock)
    assert runtime._f_cpu_time() == 12.5
    assert calls == [1]


@pytest.mark.parametrize('exception', [OSError, NotImplementedError])
def test_unavailable_clock_returns_negative(monkeypatch, exception):
    def unavailable():
        raise exception('unavailable')
    monkeypatch.setattr(runtime.time, 'process_time', unavailable)
    assert runtime._f_cpu_time() == -1.0


def test_fixture_with_monotonic_clock(monkeypatch, capsys):
    ticks = iter(range(10, 100))
    monkeypatch.setattr(runtime.time, 'process_time', lambda: next(ticks))
    source = (Path(__file__).parent / 'cases/features/cpu_time.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == [
        'True True', 'True True', 'True True True True',
        'True', 'True True', 'True True', 'call cpu_time(t0)',
    ]


@pytest.mark.parametrize('call', [
    'call cpu_time()', 'call cpu_time(t,t)', 'call cpu_time(other=t)',
    'call cpu_time(time=t,time=t)', 'call cpu_time(1.0)',
    'call cpu_time(t+1.0)', 'call cpu_time(a)', 'call cpu_time(a(:))',
    'call cpu_time(a([1]))', 'call cpu_time(i)', 'call cpu_time(unknown)',
])
def test_invalid_output_diagnosed(call):
    with pytest.raises(ValueError, match='CPU_TIME'):
        basic_f2p().transpile(f'''program main
real :: t, a(2)
integer :: i
{call}
end program
''')


def test_cpu_time_updates_host_variable(monkeypatch, capsys):
    monkeypatch.setattr(runtime.time, 'process_time', lambda: 7.5)
    exec(basic_f2p().transpile('''program main
real :: elapsed
elapsed = -1.0
call stamp()
print *, elapsed
contains
subroutine stamp()
call cpu_time(elapsed)
end subroutine
end program
'''), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == '7.5'


def test_user_procedure_named_cpu_time(capsys):
    exec(basic_f2p().transpile('''program main
real :: t
call cpu_time(t)
print *, t
contains
subroutine cpu_time(t)
real, intent(out) :: t
t = 42.0
end subroutine
end program
'''), {'__name__': '__main__'})
    assert float(capsys.readouterr().out) == 42.0
