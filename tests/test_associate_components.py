from xf2p import basic_f2p


DECLARATIONS = '''type :: item
integer :: v(4), m(2,2), offset(-1:2)
end type
type(item), target :: x,y
'''


def execute(body, capsys, declarations=DECLARATIONS):
    generated = basic_f2p().transpile('program main\nimplicit none\n' + declarations + '\n' + body + '\nend program')
    exec(generated, {'__name__': '__main__'})
    return capsys.readouterr().out.split()


def test_component_strided_section_writes_through(capsys):
    assert execute('''x%v=[1,2,3,4]
associate(a=>x%v(2:4:2))
a=a*10
end associate
print *, x%v''', capsys) == ['1','20','3','40']


def test_whole_component_alias_integer_conversion(capsys):
    assert execute('''x%v=[1,2,3,4]
associate(a=>x%v)
a=2.9
end associate
print *, x%v''', capsys) == ['2']*4


def test_scalar_component_array_element_writes_through(capsys):
    assert execute('''x%v=[1,2,3,4]
associate(a=>x%v(3))
a=a*10
end associate
print *, x%v''', capsys) == ['1','2','30','4']


def test_multidimensional_scalar_and_section(capsys):
    assert execute('''x%m=reshape([1,2,3,4],[2,2])
associate(a=>x%m(2,1), b=>x%m(:,2))
a=20
b=b*10
end associate
print *, x%m''', capsys) == ['1','20','30','40']


def test_section_selector_bounds_are_captured_on_entry(capsys):
    assert execute('''x%v=[1,2,3,4]
i=2
associate(a=>x%v(i:4:2))
i=1
a=a*10
end associate
print *, x%v''', capsys, DECLARATIONS+'integer :: i') == ['1','20','3','40']


def test_nondefault_component_bounds(capsys):
    assert execute('''x%offset=[1,2,3,4]
associate(a=>x%offset(0:2:2), b=>x%offset(-1))
a=a*10
b=9
end associate
print *, x%offset''', capsys) == ['9','20','3','40']


def test_expression_selector_is_snapshot_not_alias(capsys):
    assert execute('''x%v=[1,2,3,4]
associate(a=>x%v*2)
x%v=[9,9,9,9]
print *, a
end associate
print *, x%v''', capsys) == ['2','4','6','8']+['9']*4


def test_nested_shadowing_restores_alias(capsys):
    assert execute('''x%v=[1,2,3,4]
y%v=[5,6,7,8]
associate(a=>x%v(2:4:2))
associate(a=>y%v(1:3:2))
a=a*10
end associate
a=a*100
end associate
print *, x%v,y%v''', capsys) == ['1','200','3','400','50','6','70','8']


def test_shadowed_outer_array_and_bounds_are_restored(capsys):
    assert execute('''a=[7,8]
x%v=[1,2,3,4]
associate(a=>x%v(2:4:2))
a(1)=20
end associate
a(0)=70
print *, x%v,a''', capsys, DECLARATIONS+'integer :: a(0:1)') == ['1','20','3','4','70','8']


def test_selectors_all_use_enclosing_scope(capsys):
    assert execute('''x%v=[1,2,3,4]
associate(x=>x%v(1:2), a=>x%v(3:4))
x=x*10
a=a*100
end associate
print *, x%v''', capsys) == ['10','20','300','400']


def test_expression_array_selector_can_be_indexed(capsys):
    assert execute('''x%v=[1,2,3,4]
associate(a=>x%v*2)
x%v=[9,9,9,9]
print *, a(1),a(4)
end associate''', capsys) == ['2','8']
