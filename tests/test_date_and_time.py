import datetime
from pathlib import Path

import numpy as np
import pytest

import fortran_py_runtime as runtime
from xf2p import basic_f2p


@pytest.mark.parametrize('minutes,zone', [(-240, '-0400'), (330, '+0530'), (0, '+0000'), (-210, '-0330')])
def test_calendar_outputs_from_one_snapshot(monkeypatch, minutes, zone):
    stamp = datetime.datetime(2026, 10, 6, 9, 34, 1, 399999,
                              tzinfo=datetime.timezone(datetime.timedelta(minutes=minutes)))
    calls = []
    def clock():
        calls.append(1)
        return stamp
    monkeypatch.setattr(runtime, '_f_local_datetime', clock)
    assert runtime._f_date_and_time() == ('20261006', '093401.399', zone,
                                         [2026, 10, 6, minutes, 9, 34, 1, 399])
    assert calls == [1]


def test_unavailable_clock_and_timezone(monkeypatch):
    def unavailable():
        raise OSError('no clock')
    monkeypatch.setattr(runtime, '_f_local_datetime', unavailable)
    assert runtime._f_date_and_time(8) == (' '*8, ' '*10, ' '*5, [-9223372036854775807]*8)
    monkeypatch.setattr(runtime, '_f_local_datetime', lambda: datetime.datetime(2026, 1, 2))
    result = runtime._f_date_and_time()
    assert result[:3] == ('20260102', '000000.000', ' '*5)
    assert result[3][3] == -2147483647


def test_values_storage_and_tail():
    values = np.full(10, -1, dtype=np.int32)
    runtime._f_date_and_time_values(values, list(range(8)))
    np.testing.assert_array_equal(values, list(range(8)) + [-1,-1])
    storage = np.full(16, -1, dtype=np.int64)
    runtime._f_date_and_time_values_at(storage, np.arange(0,16,2), list(range(8)))
    np.testing.assert_array_equal(storage[::2], range(8))
    assert np.all(storage[1::2] == -1)


@pytest.mark.parametrize('values', [np.zeros(7, dtype=int), np.zeros((2,4), dtype=int), np.zeros(8), None])
def test_invalid_values_storage(values):
    with pytest.raises(ValueError, match='DATE_AND_TIME VALUES'):
        runtime._f_date_and_time_values(values, list(range(8)))


def test_small_integer_kind_rejected():
    with pytest.raises(ValueError, match='DATE_AND_TIME VALUES'):
        runtime._f_date_and_time(1)


def test_keywords_padding_sections_and_scalar_copyback(monkeypatch, capsys):
    monkeypatch.setattr(runtime, '_f_local_datetime', lambda: datetime.datetime(
        2026, 10, 6, 9, 34, 1, 399000, tzinfo=datetime.timezone.utc))
    exec(basic_f2p().transpile('''program main
character(len=12) :: date
character(len=10) :: clock
character(len=5) :: zone
integer :: values(16)
values = -1
call date_and_time(values=values(1:16:2), zone=zone, time=clock, date=date)
print *, '['//date//']', clock, zone
print *, values(1:16:2)
print *, all(values(2:16:2)==-1)
call stamp(date)
print *, '['//date//']'
contains
subroutine stamp(d)
character(len=12) :: d
call date_and_time(date=d)
end subroutine
end program
'''), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == [
        '[20261006    ]093401.399+0000', '2026 10 6 0 9 34 1 399',
        'True', '[20261006    ]',
    ]


@pytest.mark.parametrize('call', [
    'call date_and_time(date=d,date=d)', 'call date_and_time(other=d)',
    'call date_and_time(date=d,t)', 'call date_and_time(d,t,z,v,d)',
    "call date_and_time(date='12345678')", 'call date_and_time(date=v)',
    'call date_and_time(values=d)', 'call date_and_time(values=i)',
    'call date_and_time(date=d(:))', 'call date_and_time(date=labels)',
])
def test_invalid_calls_are_diagnosed(call):
    with pytest.raises(ValueError, match='DATE_AND_TIME'):
        basic_f2p().transpile(f'''program main
character(len=8) :: d,labels(2)
character(len=10) :: t
character(len=5) :: z
integer :: v(8),i
{call}
end program
''')


def test_user_procedure_shadowing(capsys):
    exec(basic_f2p().transpile('''program main
integer :: i
call date_and_time(i)
print *, i
contains
subroutine date_and_time(i)
integer, intent(out) :: i
i = 42
end subroutine
end program
'''), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == '42'


def test_short_and_array_element_character_outputs(monkeypatch, capsys):
    monkeypatch.setattr(runtime, '_f_local_datetime', lambda: datetime.datetime(
        2026, 10, 6, 9, 34, 1, tzinfo=datetime.timezone.utc))
    exec(basic_f2p().transpile('''program main
character(len=4) :: d
character(len=8) :: labels(2)
labels = 'untouched'
call date_and_time(date=d)
call date_and_time(date=labels(1))
print *, d, labels(1), labels(2)
end program
'''), {'__name__': '__main__'})
    assert capsys.readouterr().out.strip() == '202620261006untouche'


def test_fixture(monkeypatch, capsys):
    monkeypatch.setattr(runtime, '_f_local_datetime', lambda: datetime.datetime(
        2026, 10, 6, 9, 34, 1, 399000, tzinfo=datetime.timezone.utc))
    source = (Path(__file__).parent / 'cases/features/date_and_time.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert set(capsys.readouterr().out.split()) == {'True'}
