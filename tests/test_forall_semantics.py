import pytest

from xf2p import basic_f2p


def execute(declarations, body, capsys):
    source = 'program main\nimplicit none\n' + declarations + '\n' + body + '\nend program'
    generated = basic_f2p().transpile(source)
    exec(generated, {'__name__': '__main__'})
    return capsys.readouterr().out.split()


@pytest.mark.parametrize('block', [False, True])
def test_overlap_is_simultaneous_but_do_is_sequential(block, capsys):
    assignment = 'a(i)=a(i-1)'
    forall = ('forall(i=2:8)\n' + assignment + '\nend forall' if block
              else 'forall(i=2:8) ' + assignment)
    output = execute('integer :: i, a(8)', 'a=[1,2,3,4,5,6,7,8]\n' + forall +
                     '\nprint *, a\ndo i=2,8\na(i)=a(i-1)\nend do\nprint *, a', capsys)
    assert output == ['1','1','2','3','4','5','6','7'] + ['1'] * 8


def test_block_assignments_execute_in_statement_order(capsys):
    output = execute('integer :: i, a(4), b(4)', '''a=[1,2,3,4]
b=0
forall(i=2:4)
a(i)=a(i-1)
b(i)=a(i)*10
end forall
print *, a,b''', capsys)
    assert output == ['1','1','2','3','0','10','20','30']


def test_mask_is_frozen_for_whole_construct(capsys):
    output = execute('integer :: i, a(4), b(4)', '''a=[1,2,3,4]
b=0
forall(i=1:4,a(i)>2)
a(i)=-a(i)
b(i)=a(i)*10
end forall
print *, a,b''', capsys)
    assert output == ['1','2','-3','-4','0','0','-30','-40']


def test_multiple_indices_and_index_scope(capsys):
    output = execute('integer :: i,j,a(2,2)', '''i=99
j=88
a=reshape([1,2,3,4],[2,2])
forall(i=1:2,j=1:2) a(i,j)=a(j,i)
print *, a,i,j''', capsys)
    assert output == ['1','3','2','4','99','88']


def test_section_rhs_values_are_copied(capsys):
    output = execute('integer :: i,a(2,2)', '''a=reshape([1,2,3,4],[2,2])
forall(i=1:2) a(:,i)=a(:,3-i)
print *, a''', capsys)
    assert output == ['3','4','1','2']


def test_destination_indices_use_old_values(capsys):
    output = execute('integer :: i,a(4)', '''a=[2,3,4,1]
forall(i=1:4) a(a(i))=i
print *, a''', capsys)
    assert output == ['4','1','2','3']


def test_descending_and_empty_iteration_spaces(capsys):
    output = execute('integer :: i,a(4)', '''a=[1,2,3,4]
forall(i=4:2:-1) a(i)=a(i-1)
forall(i=4:1) a(i)=99
print *, a''', capsys)
    assert output == ['1','1','2','3']


@pytest.mark.parametrize('body', ['call foo(i)', 'where(a>0)', 'forall(j=1:2)', 'a(i)=>b(i)'])
def test_unsupported_bodies_are_diagnosed(body):
    with pytest.raises(ValueError, match='unsupported FORALL'):
        basic_f2p().transpile('program main\ninteger :: i,j,a(2),b(2)\nforall(i=1:2)\n' + body + '\nend forall\nend program')
