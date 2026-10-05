import copy
from pathlib import Path

import pytest

from xf2p import basic_f2p


TYPES = '''module m
type base
integer :: id = 1
integer :: samples(2) = [2,4]
end type
type, extends(base) :: child
integer :: extra = 8
end type
type, extends(child) :: leaf
integer :: tip = 9
end type
end module
'''


def types():
    namespace = {'__name__': 'extension_test'}
    exec(basic_f2p().transpile(TYPES), namespace)
    return namespace['base'], namespace['child'], namespace['leaf']


def test_parent_alias_reads_writes_and_replacement():
    base, child, _ = types()
    a, b = child(), child()
    a.id = 3
    assert a.base.id == 3 and b.id == 1
    a.base.id = 4
    assert a.id == 4
    assert a.samples is a.base.samples
    a.samples[0] = 9
    assert b.samples.tolist() == [2,4]
    a.base = base(id=7)
    assert a.id == 7 and a.extra == 8


def test_copies_do_not_alias_or_include_child_fields():
    _, child, _ = types()
    a = child()
    parent = copy.deepcopy(a.base)
    assert not hasattr(parent, 'extra')
    b = copy.deepcopy(a)
    b.base.id = 99
    b.samples[0] = 10
    assert a.id == parent.id == 1
    assert a.samples.tolist() == parent.samples.tolist() == [2,4]
    assert b.samples is b.base.samples


def test_parent_constructor_copies_and_flat_constructor_forms():
    base, child, _ = types()
    parent = base(id=3)
    a = child(parent, 10)
    a.samples[0] = 77
    assert parent.samples.tolist() == [2,4]
    for value in (child(id=5, samples=[6,7], extra=8), child(5,[6,7],8)):
        assert (value.id,value.base.id,value.extra) == (5,5,8)
        assert list(value.samples) == [6,7]
    with pytest.raises(TypeError, match='parent and inherited'):
        child(base=parent,id=1)
    with pytest.raises(TypeError, match='duplicate'):
        child(1,id=2)


def test_multilevel_parent_aliases_and_constructors():
    base, child, leaf = types()
    a = leaf(id=3,extra=4,tip=5)
    assert a.id == a.base.id == a.child.id == a.child.base.id == 3
    a.child.base.id = 6
    assert a.id == 6
    a.child = child(base(7),8)
    assert (a.id,a.extra,a.tip) == (7,8,5)
    b = leaf(11,[12,13],14,15)
    assert (b.id,b.extra,b.tip) == (11,14,15)
    assert list(b.child.base.samples) == [12,13]


@pytest.mark.parametrize('fixture, expected', [
    ('type_extension', [['3','8','3']]),
    ('type_extension_bindings', [['7','7'],['11','11','8']]),
])
def test_translated_fixture(fixture, expected, capsys):
    source = (Path(__file__).parent / f'cases/features/{fixture}.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert [line.split() for line in capsys.readouterr().out.splitlines()] == expected


def test_array_projection_and_nested_parent_assignment(capsys):
    source = (Path(__file__).parent / 'cases/features/type_extension_components.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    lines = [line.split() for line in capsys.readouterr().out.splitlines()]
    assert lines[-4:] == [
        ['10','30','10','30'], ['101','101','101','101'],
        ['100','4','100','4','8','9'], ['21','5','6','8','9'],
    ]


@pytest.mark.parametrize('header, component, message', [
    ('type, extends(missing) :: child', '', 'no translated parent'),
    ('type, extends(child) :: child', '', 'no translated parent'),
    ('type, extends(base) :: child', 'integer :: id', 'conflicts with inherited'),
])
def test_bad_parent_and_redeclared_fields_are_diagnosed(header, component, message):
    source = f'module m\ntype base\ninteger :: id\nend type\n{header}\n{component}\nend type\nend module'
    with pytest.raises(ValueError, match=message):
        basic_f2p().transpile(source)


def test_reused_translator_resets_extension_metadata():
    translator = basic_f2p()
    translator.transpile(TYPES)
    namespace = {'__name__': 'extension_reset'}
    exec(translator.transpile('module m\ntype child\ninteger :: id = 2\nend type\nend module'), namespace)
    value = namespace['child']()
    assert value.id == 2 and not hasattr(value,'base')
