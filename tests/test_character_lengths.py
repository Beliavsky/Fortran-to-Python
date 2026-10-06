from pathlib import Path

import pytest

from xf2p import basic_f2p


@pytest.mark.parametrize('declaration', [
    'character*3', 'character*(3)', 'character(len=3)', 'character(3)',
    'character*(n)', 'character(len=n)',
    'character*((n+1)/2)', 'character(len=(n+1)/2)',
])
def test_fixed_character_length_forms(declaration, capsys):
    # n=5 makes the nested-expression cases length 3, too.
    length = 5 if declaration.endswith('(n)') or declaration.endswith('=n)') else 3
    source = f'''program main
integer, parameter :: n=5
{declaration} :: text='abcdef'
print *, len(text), '['//text//']'
text='x'
print *, len(text), '['//text//']'
text='123456789'
print *, len(text), '['//text//']'
end program
'''
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == [
        f'{length} [' + 'abcdef'[:length] + ']',
        f'{length} [' + 'x'.ljust(length) + ']',
        f'{length} [' + '123456789'[:length] + ']',
    ]


def test_character_lengths_in_scopes_and_arrays(capsys):
    source = (Path(__file__).parent / 'cases/features/character_lengths.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == [
        '5 [hi   ]', '3 [abc]', '3 [x  ]', '3 [123]',
        '3 [abc] [x  ]', '3 [abc] [x  ]', '3 [x  ]',
    ]


@pytest.mark.parametrize('declaration', ['character*(*)', 'character(len=*)'])
def test_assumed_character_length_forms(declaration, capsys):
    source = f'''program main
character(len=3) :: text='abc'
call change(text)
print *, len(text), '['//text//']'
contains
subroutine change(text)
{declaration}, intent(inout) :: text
text='x'
end subroutine
end program
'''
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == ['3 [x  ]']
