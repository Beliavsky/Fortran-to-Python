from pathlib import Path

import pytest

from xf2p import basic_f2p


def test_deferred_character_lifecycle_components_save_and_fixed_length(capsys):
    source = (Path(__file__).parent / 'cases/features/deferred_length_character.f90').read_text()
    translated = basic_f2p().transpile(source)
    assert ', :)' not in translated
    exec(translated, {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == [
        '0', '6 modern', '14 modern Fortran', '8 abababab', '2 1', '0 1',
        '8 3', '8 abcdefgh', '12 box expanded', '0', '5 again', '1 a', '2 aa',
    ]


def test_deferred_character_function_result_and_block(capsys):
    source = '''program test
character(len=4) :: s
s = 'keep'
block
character(len=:), allocatable :: s
s = 'longer'
print *, len(s), s
end block
print *, len(s), s
print *, message()
contains
function message() result(text)
character(len=:), allocatable :: text
text = 'generated'
end function
end program
'''
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == ['6 longer', '4 keep', 'generated']


@pytest.mark.parametrize('declaration, expected', [
    ('character(:), allocatable :: s(:)', 'array assignment'),
    ('character(:), pointer :: s', 'pointer assignment'),
])
def test_unsupported_deferred_character_assignments_are_rejected(declaration, expected):
    with pytest.raises(ValueError, match=expected):
        basic_f2p().transpile(f"program test\n{declaration}\ns = 'abc'\nend program\n")
