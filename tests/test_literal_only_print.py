import pytest

from xf2p import basic_f2p


@pytest.mark.parametrize(('statement', 'expected'), [
    ('print "(\'hello\')"', 'hello\n'),
    ('print \'("bye")\'', 'bye\n'),
    ('print "(2x,\'hi\',/,2(\'x\',1x))"', '  hi\nx x \n'),
    ('print "(\'prefix\',:,\'suffix\')"', 'prefix\n'),
    ('print "(\'prefix\',i4,\'suffix\')"', 'prefix\n'),
    ('print "()"', '\n'),
    ('print "(/)"', '\n\n'),
    ('print "(\'don\'\'t\')"', "don't\n"),
    ('print \'("a""b")\'', 'a"b\n'),
])
def test_itemless_print(statement, expected, capsys):
    generated = basic_f2p().transpile('program main\n' + statement + '\nend program')
    exec(generated, {'__name__': '__main__'})
    assert capsys.readouterr().out == expected


def test_itemless_print_in_single_line_if(capsys):
    source = '''program main
if (.true.) print "('yes')"
if (.false.) print "('no')"
end program'''
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out == 'yes\n'


def test_unsupported_itemless_format_is_diagnosed():
    with pytest.raises(ValueError, match='unsupported itemless PRINT format'):
        basic_f2p().transpile('program main\nprint "(t5,\'hello\')"\nend program')
