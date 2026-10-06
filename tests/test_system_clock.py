from pathlib import Path

import pytest

import fortran_py_runtime as runtime
from xf2p import basic_f2p


@pytest.mark.parametrize('kind', [1, 2, 4, 8, 16])
def test_integer_kinds_and_wrap(monkeypatch, kind):
    maximum = (1 << (8 * kind - 1)) - 1
    rate = min(maximum, 1_000_000_000 if kind >= 8 else 1_000)
    monkeypatch.setattr(runtime.time, 'monotonic_ns', lambda: 2_500_000_000)
    assert runtime._f_system_clock([kind]) == ((rate * 5 // 2) % (maximum + 1), rate, maximum)
    monkeypatch.setattr(runtime.time, 'monotonic_ns', lambda: (maximum + 1) * 1_000_000_000)
    assert runtime._f_system_clock([kind])[0] == 0


def test_mixed_integer_kinds_fit_every_output(monkeypatch):
    monkeypatch.setattr(runtime.time, 'monotonic_ns', lambda: 1_000_000_000)
    assert runtime._f_system_clock([8, 1, 4]) == (127, 127, 127)


@pytest.mark.parametrize('exception', [OSError, NotImplementedError, AttributeError])
def test_unavailable_clock(monkeypatch, exception):
    def unavailable():
        raise exception('unavailable')
    monkeypatch.setattr(runtime.time, 'monotonic_ns', unavailable)
    assert runtime._f_system_clock([4]) == (-2147483647, 0, 0)


def test_fixture_reads_clock_once_per_call(monkeypatch, capsys):
    calls = []
    def clock():
        calls.append(1)
        return 1_000_000_000
    monkeypatch.setattr(runtime.time, 'monotonic_ns', clock)
    source = (Path(__file__).parent / 'cases/features/system_clock.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == [
        'True True True True', 'True True True', 'True True', 'True True True',
        'True True True True', 'True True True', 'True', 'True',
        'True True', 'True True True',
    ]
    assert len(calls) == 13


@pytest.mark.parametrize('call', [
    'call system_clock(c,r,m,c)', 'call system_clock(other=c)',
    'call system_clock(count=c,count=c)', 'call system_clock(count=c,r)',
    'call system_clock(1)', 'call system_clock(c+1)',
    'call system_clock(a)', 'call system_clock(a(:))',
    'call system_clock(a([1]))', 'call system_clock(t)',
    'call system_clock(count_max=t)', 'call system_clock(count_rate=flag)',
    'call system_clock(unknown)',
])
def test_invalid_outputs_diagnosed(call):
    with pytest.raises(ValueError, match='SYSTEM_CLOCK'):
        basic_f2p().transpile(f'''program main
integer :: c,r,m,a(2)
real :: t
logical :: flag
{call}
end program
''')


def test_user_procedure_named_system_clock(capsys):
    exec(basic_f2p().transpile('''program main
integer :: c
call system_clock(c)
print *, c
contains
subroutine system_clock(c)
integer, intent(out) :: c
c = 42
end subroutine
end program
'''), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == '42'


def test_kind8_alias_and_real_rate(monkeypatch, capsys):
    monkeypatch.setattr(runtime.time, 'monotonic_ns', lambda: 1_250_000_000)
    exec(basic_f2p().transpile('''program main
use iso_fortran_env, only: int64
integer(int64) :: c,m
double precision :: r
call system_clock(c,r,m)
print *, c, int(r), m
end program
'''), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == '1250000000 1000000000 9223372036854775807'
