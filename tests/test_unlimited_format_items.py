from pathlib import Path

import pytest

from xf2p import basic_f2p, _fortran_format_expr


def execute(source):
    namespace = {'__name__': '__main__'}
    exec(basic_f2p().transpile(source), namespace)
    return namespace


def test_scalar_array_matrix_and_internal_write(capsys):
    source = (Path(__file__).parent / 'cases/features/unlimited_format_items.f90').read_text()
    execute(source)
    assert capsys.readouterr().out == (
        ' 1 2 3 4 5\nmatrix 0 1 2 3 4 5\n1,2,3,4,5\n'
        '1 2;3 4;5 \n1,2,3,4,5\n\n1:2:3:4:5\n1,2,3,4,5\n'
    )


@pytest.mark.parametrize('fmt,items,expected', [
    ('(*(i0))', [1,2,3], '123'),
    ('(*(i0,","))', [1,2], '1,2,'),
    ('(*(i0,:,","))', [1,2], '1,2'),
    ('(*(i0,:,","))', [], ''),
    ('(*(1x,i0))', [], ' '),
    ('(*(2(i0,:,",")))', [1,2,3], '1,2,3'),
    ('(*(i0,:,"/",i0,:,";"))', [1,2,3], '1/2;3'),
    ('(*(i0,:,"/",i0,:,";"))', [1,2,3,4], '1/2;3/4'),
    ('(*(i0,1x,f4.1,:,";"))', [1,2.0,3,4.0], '1  2.0;3  4.0'),
    ('(*(a,:,"|"))', ['ab','cd'], 'ab|cd'),
])
def test_unlimited_group_cycles(fmt, items, expected):
    namespace = execute('program main\nend program\n')
    namespace['values'] = items
    expression = _fortran_format_expr(repr(fmt), ['values'])
    assert eval(expression, namespace) == expected


def test_each_output_expression_evaluated_once(capsys):
    execute('''program main
integer :: counter=0
print '(*(1x,i0))', next_value(),next_value(),next_value()
print *,counter
contains
integer function next_value()
counter=counter+1
next_value=counter
end function
end program
''')
    assert capsys.readouterr().out.splitlines() == [' 1 2 3', '3']


def test_large_group_reports_limit_instead_of_expanding_unbounded_code():
    with pytest.raises(ValueError, match='128 data descriptors'):
        _fortran_format_expr("'(*(129i0))'", ['values'])
