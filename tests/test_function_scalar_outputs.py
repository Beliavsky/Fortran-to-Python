import pytest

from xf2p import basic_f2p


FUNCTION = '''integer function f(i) result(r)
integer :: i
i=i*10
r=i
end function
'''


def execute(statements, capsys, functions=FUNCTION, declarations='integer :: i, j'):
    source = ('module m\nimplicit none\ncontains\n' + functions +
              'end module\nprogram main\nuse m\nimplicit none\n' +
              declarations + '\n' + statements + '\nend program\n')
    generated = basic_f2p().transpile(source)
    compile(generated, '<translation>', 'exec')
    exec(generated, {'__name__': '__main__'})
    return capsys.readouterr().out.split()


def test_function_updates_scalar_actual(capsys):
    assert execute('i=3\nj=f(i)\nprint *, i,j', capsys) == ['30', '30']


def test_function_early_return_and_explicit_intent(capsys):
    functions = '''integer function f(i) result(r)
integer, intent(inout) :: i
i=i*10
r=i
return
r=-1
end function
'''
    assert execute('i=3\nj=f(i)\nprint *, i,j', capsys, functions) == ['30', '30']


def test_nested_function_expression_and_keyword(capsys):
    assert execute('i=2\nj=abs(f(i=i))+1\nprint *, i,j', capsys) == ['20', '21']


def test_function_calls_are_not_hoisted_from_loop_test(capsys):
    functions = '''integer function f(i) result(r)
integer :: i
i=i+1
r=i
end function
'''
    assert execute('i=0\ndo while (f(i)<3)\nend do\nprint *, i', capsys, functions) == ['3']


def test_function_forwarding_propagates_output(capsys):
    functions = '''integer function outer(i) result(r)
integer :: i
r=f(i)
end function
''' + FUNCTION + '''subroutine update(i)
integer :: i, n
n=outer(i)
end subroutine
'''
    assert execute('i=3\ncall update(i)\nprint *, i', capsys, functions) == ['30']


def test_array_element_actual(capsys):
    assert execute('i=[2,3]\nj=f(i(2))\nprint *, i,j', capsys,
                   declarations='integer :: i(2), j') == ['2', '30', '30']


def test_element_destination_captured_before_other_output_changes(capsys):
    functions = '''integer function f(index, value) result(r)
integer :: index, value
index=2
value=9
r=7
end function
'''
    assert execute('i=1\na=[3,4]\nj=f(i,a(i))\nprint *, i,a,j', capsys, functions,
                   declarations='integer :: i, a(2), j') == ['2', '9', '4', '7']


def test_optional_output_may_be_omitted(capsys):
    functions = '''integer function f(i, extra) result(r)
integer :: i
integer, optional :: extra
i=i+1
if (present(extra)) extra=8
r=i
end function
'''
    assert execute('i=1\nj=f(i)\nprint *, i,j', capsys, functions) == ['2', '2']


def test_read_only_function_still_accepts_expression(capsys):
    functions = '''integer function f(i) result(r)
integer :: i
r=i*10
end function
'''
    assert execute('j=f(1+2)\nprint *, j', capsys, functions) == ['30']


def test_call_text_in_string_does_not_define_dummy(capsys):
    functions = FUNCTION + '''integer function label(i) result(r)
integer :: i
print *, 'f(i)'
r=i
end function
'''
    assert execute('j=label(3)\nprint *, j', capsys, functions) == ['f(i)', '3']


def test_modified_function_dummy_requires_definable_actual():
    with pytest.raises(ValueError, match='definable actual'):
        basic_f2p().transpile('module m\ncontains\n' + FUNCTION +
                             'end module\nprogram main\nuse m\ninteger :: j\nj=f(3)\nend program')
