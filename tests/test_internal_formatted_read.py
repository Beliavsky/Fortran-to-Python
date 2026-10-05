import pytest

from xf2p import basic_f2p


def execute(source, capsys):
    generated = basic_f2p().transpile(source)
    exec(generated, {'__name__': '__main__'})
    return capsys.readouterr().out.strip()


def test_date_read_is_not_silently_omitted(capsys):
    assert execute('''program demo
character(len=10) :: s
integer :: year, month, day
s = '2002-07-30'
read(s, '(i4,1x,i2,1x,i2)') year, month, day
print *, year, month, day
end program
''', capsys) == '2002 7 30'


@pytest.mark.parametrize('record', ['2002,07,30', '2002 07 30', '2002 , 07, 30', '2002,07 30', '2002,07,30,', '2002,07,30,unused'])
def test_list_directed_date_separators(capsys, record):
    source = f'''program demo
character(len=20) :: s
integer :: year, month, day, ios
s = '{record}'
read(s, *, iostat=ios) year, month, day
print *, year, month, day, ios
end program
'''
    assert execute(source, capsys) == '2002 7 30 0'


def test_quoted_character_commas_and_doubled_quotes(capsys):
    source = '''program demo
character(len=30) :: s
character(len=10) :: value
integer :: n
s = '"a,b c", 7'
read(s, *) value, n
print *, trim(value), n
s = '"a""b", 8'
read(s, *) value, n
print *, trim(value), n
end program
'''
    assert execute(source, capsys).splitlines() == ['a,b c 7', 'a"b 8']


def test_quoted_integer_input_is_not_accepted(capsys):
    source = '''program demo
character(len=10) :: s
integer :: n, ios
n = 99
s = '"123"'
read(s, *, iostat=ios) n
print *, ios > 0, n
end program
'''
    assert execute(source, capsys) == 'True 99'


@pytest.mark.parametrize('record', ['2002,,30', ',2002,07,30', '3*2002', '2002/'])
def test_unsupported_list_directed_syntax_is_not_misread(capsys, record):
    source = f'''program demo
character(len=20) :: s
integer :: year, month, day, ios
year = 99
s = '{record}'
read(s, *, iostat=ios) year, month, day
print *, ios > 0, year
end program
'''
    assert execute(source, capsys) == 'True 99'


@pytest.mark.parametrize('declaration,record,fmt,expected', [
    ('integer', ' 1 2', '(i4)', '12'),
    ('integer', ' -12', '(i4.2)', '-12'),
    ('integer', '    ', '(i4)', '0'),
    ('real', '001250', '(f6.2)', '12.5'),
    ('real', '123E+02', '(e7.2)', '123.0'),
    ('real', '1.25D+02', '(d8.2)', '125.0'),
    ('real', '1.2+003', '(g7.2)', '1200.0'),
    ('logical', '.false.', '(l7)', 'False'),
    ('character(len=3)', 'abcdef', '(a6)', 'def'),
    ('character(len=3)', 'ab', '(a2)', 'ab'),
    ('character(len=3)', 'abc', '(a)', 'abc'),
])
def test_scalar_edit_descriptors(capsys, declaration, record, fmt, expected):
    source = f'''program demo
character(len={len(record)}) :: s
{declaration} :: value
s = '{record}'
read(unit=s, fmt='{fmt}') value
print *, value
end program
'''
    assert execute(source, capsys) == expected


def test_repeats_elements_components_and_record_padding(capsys):
    source = '''program demo
type :: fields
    character(len=4) :: text
    integer :: value
end type
type(fields) :: h
integer :: a(2), tail, ios
character(len=10) :: message
h%text = '1234'
read(h%text, '(2i2,i2)', iostat=ios, iomsg=message) a(1), h%value, tail
print *, a(1), h%value, tail, ios
end program
'''
    assert execute(source, capsys) == '12 34 0 0'


def test_invalid_field_iostat_and_iomsg(capsys):
    source = '''program demo
character(len=4) :: s
character(len=30) :: message
integer :: n, ios
n = 42
s = 'oops'
read(s, '(i4)', iostat=ios, iomsg=message) n
print *, ios > 0, len_trim(message) > 0, len(message), n
s = ' 123'
message = 'unchanged'
read(s, '(i4)', iostat=ios, iomsg=message) n
print *, ios, n, trim(message)
end program
'''
    assert execute(source, capsys).splitlines() == ['True True 30 42', '0 123 unchanged']


def test_invalid_field_without_iostat_raises(capsys):
    with pytest.raises(ValueError, match='Invalid integer input'):
        execute("program demo\ncharacter(len=4) :: s='oops'\ninteger :: n\nread(s,'(i4)') n\nend program", capsys)


@pytest.mark.parametrize('statement', [
    "read(s,'(bz,i4)') n", "read(s,'(t2,i4)') n", "read(s,'(2(i2))') n",
    "read(s,'(i4/)') n", "read(s,'(i0)') n", "read(s,'(i4)',end=100) n",
    "read(s,'(i4)',advance='no') n", "read(s,fmt) n", "read(s,10) n",
    "read(s,'(i2)') n, m", "read(s,'(i2)') a", "read(s,'(i2)') a(:)",
    "read(records,'(i4)') n", "read(s) n", "read(s,'(f4.1)') n",
    "read(s,'(i2)') a([1,2])", "read(s,'(i2)') a(indices)",
    "read(s,'(i4)',iomsg=message) n", "read(s,*,iomsg=message) n",
])
def test_unsupported_reads_are_diagnosed(statement):
    source = f'''program demo
character(len=4) :: s='1234', records(2), message
character(len=8) :: fmt='(i4)'
integer :: n, m, a(2), indices(2)
{statement}
end program
'''
    with pytest.raises(ValueError, match='READ'):
        basic_f2p().transpile(source)
