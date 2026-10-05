from pathlib import Path

import pytest

from xf2p import basic_f2p, lower_enum_declarations, split_fortran_comment, collapse_fortran_continuations


def execute(source, capsys, translator=None):
    translator = translator or basic_f2p()
    generated = translator.transpile(source)
    namespace = {'__name__': 'enum_test'}
    exec(generated, namespace)
    namespace['main']()
    return capsys.readouterr().out.split(), generated, translator


def test_native_fixture_translation(capsys):
    source = (Path(__file__).parent / 'cases/features/enumerators.f90').read_text()
    output, generated, translator = execute(source, capsys)
    assert output == ['0', '1', '-3', '-2', '7', '8', '7',
                      '0', '1', '5', '-2', '40', 'green', '101', '200', '201', '5']
    assert 'green: Final[int] = red + 1' in generated
    assert 'Enum(' not in generated
    assert set(translator._module_variable_symbols['palette']) == {'green'}
    assert 'parameter' in translator._module_variable_symbols['palette']['green']['attrs_l']


@pytest.mark.parametrize('header', ['enum, bind(c)', 'ENUM , BIND ( C )'])
@pytest.mark.parametrize('declaration', ['enumerator :: a = -2, b, c = a + 9, d',
                                       'enumerator a = -2, b, c = a + 9, d'])
def test_explicit_implicit_and_negative_values(header, declaration, capsys):
    source = f'program demo\n{header}\n{declaration}\nend enum\nprint *, a,b,c,d\nend program'
    assert execute(source, capsys)[0] == ['-2', '-1', '7', '8']


def test_semicolon_and_continuation_declarations(capsys):
    source = """program demo
enum, bind(c); enumerator :: a, b = 10
enumerator :: c, &
   d = b + 2; end enum
print *, a,b,c,d
print *, 'enum; enumerator; end enum'
end program
"""
    assert execute(source, capsys)[0] == ['0', '10', '11', '12', 'enum;', 'enumerator;', 'end', 'enum']


def test_only_import_does_not_capture_local_variable(capsys):
    source = """module colors
enum, bind(c)
enumerator :: hidden = 99, visible = 7
end enum
end module
program demo
use colors, only: visible
integer :: hidden
hidden = 3
print *, visible, hidden
end program
"""
    assert execute(source, capsys)[0] == ['7', '3']


def test_function_and_subroutine_enumerators_are_local(capsys):
    source = """program demo
enum, bind(c)
enumerator :: flag = 10
end enum
call show()
print *, get_flag(), flag
contains
subroutine show()
enum, bind(c)
enumerator :: flag = 20
end enum
print *, flag
end subroutine
integer function get_flag()
enum, bind(c)
enumerator :: flag = 30
end enum
get_flag = flag
end function
end program
"""
    assert execute(source, capsys)[0] == ['20', '30', '10']


@pytest.mark.parametrize('body, message', [
    ('enumerator :: a', 'outside ENUM'),
    ('end enum', 'without ENUM'),
    ('enum, bind(c)\nenumerator :: a', 'without END ENUM'),
    ('enum, bind(c)\nend enum', 'at least one'),
    ('enum, bind(c)\nenum, bind(c)', 'nested ENUM'),
    ('enum\nenumerator :: a\nend enum', 'Only anonymous'),
    ('enum, bind(c)\nenumerator :: a, a\nend enum', 'duplicate ENUMERATOR'),
    ('enum, bind(c)\nenumerator :: a=\nend enum', 'malformed ENUMERATOR'),
    ('enum, bind(c)\nenumerator ::\nend enum', 'empty ENUMERATOR'),
    ('enum, bind(c)\ninteger :: a\nend enum', 'within ENUM'),
])
def test_bad_enum_declarations_are_diagnosed(body, message):
    with pytest.raises(ValueError, match=message):
        basic_f2p().transpile(f'program demo\n{body}\nend program')


@pytest.mark.parametrize('second_declaration', [
    'enum, bind(c)\nenumerator :: flag = 2\nend enum',
    'integer, parameter :: flag = 2', 'integer :: flag',
])
def test_cross_module_namespace_collision_is_diagnosed(second_declaration):
    source = f'''module first
enum, bind(c)
enumerator :: flag = 1
end enum
end module
module second
{second_declaration}
end module
program demo
end program'''
    with pytest.raises(ValueError, match='separate module namespaces'):
        basic_f2p().transpile(source)


def test_renamed_use_has_existing_explicit_diagnostic():
    source = '''module colors
enum, bind(c)
enumerator :: green = 2
end enum
end module
program demo
use colors, only: local => green
print *, local
end program'''
    with pytest.raises(ValueError, match='renamed USE-associated'):
        basic_f2p().transpile(source)


def test_prepass_preserves_comments_and_resets_each_enum():
    source = 'enum, bind(c)\nenumerator :: a = 7, b ! colors\nend enum\nenum, bind(c)\nenumerator :: c\nend enum'
    lines = collapse_fortran_continuations([split_fortran_comment(line) for line in source.splitlines()])
    lowered, modules = lower_enum_declarations(lines)
    assert ('integer, parameter :: a = 7', 'colors') in lowered
    assert ('integer, parameter :: b = a + 1', 'colors') in lowered
    assert ('integer, parameter :: c = 0', '') in lowered
    assert modules == {}


def test_reused_translator_does_not_retain_enumerator_state(capsys):
    translator = basic_f2p()
    for value in [7, 3]:
        source = f'program demo\nenum, bind(c)\nenumerator :: a={value}, b\nend enum\nprint *, a,b\nend program'
        assert execute(source, capsys, translator)[0] == [str(value), str(value + 1)]


def test_enum_keywords_as_variable_names(capsys):
    source = '''program demo
integer :: enum(1), enumerator(1)
enum(1) = 7
enumerator(1) = 8
print *, enum(1), enumerator(1)
end program'''
    assert execute(source, capsys)[0] == ['7', '8']


def test_integer_model_inquiry_uses_enumerator_type(capsys):
    source = '''program demo
enum, bind(c)
enumerator :: zero
end enum
print *, huge(zero), digits(zero)
end program'''
    output, generated, _ = execute(source, capsys)
    assert output == ['2147483647', '31']
    assert 'integer_kind=4' in generated
