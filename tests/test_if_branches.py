"""Fortran ELSE IF spellings must retain branch selection and nesting."""
import pytest

from xf2p import basic_f2p


@pytest.mark.parametrize('keyword', ['elseif', 'else if', 'ELSEIF', 'ELSE IF'])
def test_else_if_spellings_preserve_nested_branches(keyword, capsys):
    source = f'''program branches
integer :: i
do i = 1, 6
   if (i == 1) then
      print *, 'first', i
   {keyword} (i <= 3) then
      if (i == 2) then
         print *, 'nested first', i
      {keyword} (i == 3) then
         print *, 'nested second', i
      end if
   {keyword} (i == 4) then
      print *, 'fourth', i
   else
      print *, 'last', i
   endif
   print *, 'after', i
enddo
print *, 'done'
end program branches'''
    generated = basic_f2p().transpile(source)
    assert generated.count('elif ') == 3
    namespace = {'__name__': 'branch_test'}
    exec(generated, namespace)
    namespace['main']()
    assert [line.split() for line in capsys.readouterr().out.splitlines()] == [
        ['first', '1'], ['after', '1'],
        ['nested', 'first', '2'], ['after', '2'],
        ['nested', 'second', '3'], ['after', '3'],
        ['fourth', '4'], ['after', '4'],
        ['last', '5'], ['after', '5'],
        ['last', '6'], ['after', '6'], ['done'],
    ]


def test_compact_named_enddo_closes_loop(capsys):
    source = '''program named_loop
integer :: i
outer: do i = 1, 2
   print *, i
enddo outer
print *, 'done'
end program named_loop'''
    namespace = {'__name__': 'branch_test'}
    exec(basic_f2p().transpile(source), namespace)
    namespace['main']()
    assert capsys.readouterr().out.split() == ['1', '2', 'done']
