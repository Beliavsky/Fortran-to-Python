from pathlib import Path

import pytest

from xf2p import basic_f2p


@pytest.mark.parametrize('literal,expected', [
    ('.true._1', 'True'), ('.false._8', 'False'),
    ('.TRUE._LK', 'True'), ('.False._logical_kind', 'False'),
])
def test_kind_suffix_is_removed_from_python_value(literal, expected):
    assert basic_f2p().translate_expr(literal, set()) == expected


def test_suffixed_values_arrays_and_inquiries(capsys):
    source = (Path(__file__).parent / 'cases/features/logical_kind_literals.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == [
        'True False True False True', '1 8 8', 'True False',
        '.true._lk stays literal text',
    ]


def test_operator_words_and_suffixes_inside_strings_are_unchanged():
    assert basic_f2p().translate_expr("'.true._1 .and. .false._lk'", set()) == repr('.true._1 .and. .false._lk')
