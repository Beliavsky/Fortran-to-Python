import ast

from xf2p import basic_f2p


def test_program_internal_counter_is_per_main_invocation(capsys):
    source = '''program host
integer :: count
count = 0
call tick()
call tick()
print *, count
contains
subroutine tick()
count = count + 1
end subroutine tick
end program'''
    generated = basic_f2p().transpile(source)
    tree = ast.parse(generated)
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    tick = next(node for node in main.body if isinstance(node, ast.FunctionDef) and node.name == 'tick')
    assert any(isinstance(node, ast.Nonlocal) and 'count' in node.names for node in tick.body)
    namespace = {'__name__': 'host_test'}
    exec(generated, namespace)
    namespace['main']()
    namespace['main']()
    assert capsys.readouterr().out.split() == ['2', '2']


def test_declared_local_shadows_host_counter(capsys):
    source = '''program host
integer :: count
count = 7
call shadow()
print *, count
contains
subroutine shadow()
integer :: count
count = 99
print *, count
end subroutine shadow
end program'''
    namespace = {'__name__': 'host_test'}
    exec(basic_f2p().transpile(source), namespace)
    namespace['main']()
    assert capsys.readouterr().out.split() == ['99', '7']
