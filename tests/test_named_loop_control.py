from pathlib import Path

import pytest

from xf2p import basic_f2p


def execute(source, capsys):
    namespace = {'__name__': 'loop_test'}
    exec(basic_f2p().transpile(source), namespace)
    namespace['main']()
    return capsys.readouterr().out.splitlines()


def test_named_loop_exit_cycle_and_termination_values(capsys):
    source = (Path(__file__).parent / 'cases/features/named_loop_control.f90').read_text()
    lines = [line.split() for line in execute(source, capsys)]
    assert lines == [['63', '3', '5'], ['10', '5', '1', '2'],
                     ['6', '3', '2'], ['2', '1'], ['4', '0'], ['1']]


def test_named_loop_in_procedure_with_block_and_select_case(capsys):
    source = '''program p
call run()
contains
subroutine run()
integer :: i, j, total
total = 0
outer: do i = 1, 4
inner: do j = 1, 3
block
integer :: value
value = i
select case (i)
case (2)
cycle outer
case (3)
exit outer
case default
total = total + value
end select
end block
end do inner
end do outer
print *, total, i, j
end subroutine
end program'''
    assert execute(source, capsys)[0].split() == ['3', '3', '1']


@pytest.mark.parametrize('statement, message', [
    ('exit missing', 'unknown DO construct'),
    ('cycle missing', 'unknown DO construct'),
    ('end do missing', 'does not match'),
])
def test_invalid_construct_names_are_rejected(statement, message):
    with pytest.raises(ValueError, match=message):
        basic_f2p().transpile(f'program p\ninteger :: i\nouter: do i=1,2\n{statement}\nend do outer\nend program')


def test_named_concurrent_is_explicitly_rejected():
    with pytest.raises(ValueError, match='named DO CONCURRENT'):
        basic_f2p().transpile('program p\ninteger :: i\nouter: do concurrent(i=1:2)\nend do outer\nend program')


def test_reusing_transpiler_resets_loop_targets(capsys):
    translator = basic_f2p()
    source = '''program p
integer :: i
outer: do i=1,2
exit outer
end do outer
print *, i
end program'''
    assert translator.transpile(source) == translator.transpile(source)
