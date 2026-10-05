import pytest

from xf2p import basic_f2p


def execute(declarations, body, capsys):
    source = 'program main\nimplicit none\n' + declarations + '\n' + body + '\nend program'
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    return capsys.readouterr().out.split()


@pytest.mark.parametrize('otherwise', ['elsewhere', 'else where', 'elsewhere region', 'else where region'])
def test_named_where_and_elsewhere_spellings(otherwise, capsys):
    output = execute('integer :: v(4)=[10,20,30,40]', f'''region: where(v<25)
v=10*v
{otherwise}
v=-1
end where region
print *, v''', capsys)
    assert output == ['100', '200', '-1', '-1']


def test_logical_array_mask_is_copied(capsys):
    output = execute('logical :: mask(4), result(4)', '''mask=[.true.,.false.,.true.,.false.]
result=.false.
where(mask)
mask=.false.
result=.true.
elsewhere
result=.false.
end where
print *, mask,result''', capsys)
    assert output == ['False']*4 + ['True','False','True','False']


def test_masked_elsewhere_is_evaluated_at_branch_entry(capsys):
    output = execute('integer :: v(4)=[1,2,3,4]', '''region: where(v<2)
v=10
else where (v<4) region
v=20
elsewhere region
v=-1
endwhere region
print *, v''', capsys)
    assert output == ['10', '20', '20', '-1']


def test_nested_named_where_preserves_parent_mask(capsys):
    output = execute('integer :: v(4)=[-2,-1,1,2]', '''outer: where(v<0)
inner: where(v<-1)
v=100
elsewhere inner
v=200
end where inner
elsewhere outer
v=-1
endwhere outer
print *, v''', capsys)
    assert output == ['100', '200', '-1', '-1']


def test_single_line_where(capsys):
    assert execute('integer :: v(4)=[1,2,3,4]',
                   'where(v<3) v=10*v\nprint *, v', capsys) == ['10','20','3','4']


@pytest.mark.parametrize('ending', ['elsewhere wrong', 'else where (v>0) wrong', 'endwhere wrong'])
def test_mismatched_construct_names_are_diagnosed(ending):
    with pytest.raises(ValueError, match='WHERE construct name mismatch'):
        basic_f2p().transpile('program main\ninteger :: v(2)\nregion: where(v>0)\nv=1\n' + ending + '\nend where region\nend program')


@pytest.mark.parametrize('statement', ['elsewhere', 'else where', 'endwhere'])
def test_unmatched_where_clauses_are_diagnosed(statement):
    with pytest.raises(ValueError, match='without an active WHERE'):
        basic_f2p().transpile('program main\n' + statement + '\nend program')
