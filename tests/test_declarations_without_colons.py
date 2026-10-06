from pathlib import Path

import pytest

from xf2p import basic_f2p, parse_decl, parse_decl_items


@pytest.mark.parametrize('source,expected', [
    ('integer(8) a,b', ('integer', '(8)', 'a,b')),
    ('real x(3)', ('real', '', 'x(3)')),
    ('logical b', ('logical', '', 'b')),
    ('real(kind=selected_real_kind(15)) x', ('real', '(kind=selected_real_kind(15))', 'x')),
    ('double precision y', ('real', '(kind=8)', 'y')),
    ('DOUBLE COMPLEX zz', ('complex', '(kind=8)', 'zz')),
    ('character*3 text', ('character', '*3', 'text')),
    ('character*((n+1)/2) text', ('character', '*((n+1)/2)', 'text')),
    ('character(len=3) text', ('character', '(len=3)', 'text')),
    ('integer*8 n', ('integer', '*8', 'n')),
])
def test_optional_double_colon_declarations(source, expected):
    assert parse_decl(source) == expected


@pytest.mark.parametrize('source', [
    'real = 3', 'integer(1) = 3', 'real(x)', 'print *, real(x)',
    'call real(x)', 'real function f(x)', 'pure integer function f(x)',
    'double precision function f(x)', 'complex function f(x) result(z)',
    'character(len=3) function f()', 'integer_count=3',
    'real, dimension(3) x', 'integer n=3',
])
def test_executable_statements_and_procedure_headers_are_not_declarations(source):
    assert parse_decl(source) is None


def test_nested_array_bounds_and_multiple_entities():
    ftype, attrs, rest = parse_decl('real(8) a(-2:2),b(2,size(a,1))')
    assert (ftype, attrs) == ('real', '(8)')
    assert parse_decl_items(rest) == [('a', '-2:2', None), ('b', '2,size(a,1)', None)]


def test_execution_and_character_lengths(capsys):
    source = (Path(__file__).parent / 'cases/features/declarations_without_colons.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == [
        '1 8 2 70', '16 9223372036854775807',
        '4 8 8 4 8', '-1 1 4 6', 'True', 'abc', 'hell', '3 4',
        '11 12', '8 4 8 3',
    ]
