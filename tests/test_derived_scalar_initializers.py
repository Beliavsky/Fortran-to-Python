"""Derived declaration values are copies, with implicit SAVE in procedures."""
from pathlib import Path

from xf2p import basic_f2p


def test_constructor_initializers_and_saved_local_state(capsys):
    source = (Path(__file__).parent / 'cases/features/derived_scalar_initializers.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert [line.split() for line in capsys.readouterr().out.splitlines()] == [
        ['10.0', '20.0'], ['3.0', '4.0'], ['3.0', '4.0'],
        ['99', '10', '10'], ['30', '40'], ['31', '42'], ['50'], ['51'],
    ]


def test_initializer_copies_nested_array_components():
    source = '''module m
type record
integer :: values(2)
end type record
type(record), parameter :: seed = record([1,2])
type(record) :: first = seed, second = seed
end module m'''
    namespace = {'__name__': 'test_initializers'}
    exec(basic_f2p().transpile(source), namespace)
    namespace['first'].values[0] = 99
    assert namespace['second'].values.tolist() == [1, 2]
    assert namespace['seed'].values.tolist() == [1, 2]


def test_uninitialized_derived_variable_keeps_component_defaults():
    source = '''module m
type record
integer :: value = 7
end type record
type(record) :: uninitialized
end module m'''
    namespace = {'__name__': 'test_initializers'}
    exec(basic_f2p().transpile(source), namespace)
    assert namespace['uninitialized'].value == 7
