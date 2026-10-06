# Fortran-to-Python syntax guide

This guide explains how common numerical Fortran constructs correspond to
Python and NumPy, and where a direct-looking translation changes their meaning.
It complements the [README](README.md) and [feature coverage](tests/FEATURE_COVERAGE.txt).
It is not a specification of complete Fortran support.

Python snippets below are simplified equivalents unless explicitly described as
generated code. They assume `import numpy as np`; runtime examples additionally
import the named helpers from `fortran_py_runtime`. Actual `xf2p.py` output can
contain initialization, copying, type conversion, and helper calls omitted here.
Names of generated helpers are implementation details, not a stable public API.

## Declarations, names, and arithmetic

| Fortran | Python equivalent or important difference |
| --- | --- |
| `integer :: i` | Python `int`, or an integer NumPy array for array declarations. |
| `real :: x` | Python floating-point values; default Fortran REAL precision is not generally reproduced. |
| `complex :: z` | Python `complex` or a complex NumPy array. |
| `logical :: flag` | `bool` or a Boolean NumPy array. |
| `integer, parameter :: n = 10` | A Python binding initialized to `10`; Python does not enforce immutability. |
| `x ** 2` | `x ** 2`. |
| `a / b` for INTEGER operands | Truncation toward zero, not Python `/` or negative-value floor division `//`. |
| `mod(a,p)` | Remainder with the sign of `a`; not generally Python `%`. |
| `modulo(a,p)` | Remainder with the sign of `p`, like Python `%` for ordinary integer operands. |

For example, Fortran `-7 / 3` is `-2`, whereas Python `-7 // 3` is `-3`.
The translator uses helpers such as `_xf2p_div`, `_xf2p_mod`, and
`_xf2p_modulo` to retain the relevant arithmetic rules. Integer assignment
also requires truncation when the RHS is real; array conversion must be
elementwise rather than `int(array)`.

Fortran names are case-insensitive: `Total` and `total` name the same entity.
Python names are case-sensitive. The translator normalizes Fortran identifiers;
do not introduce distinct Python bindings that differ only in capitalization
when manually revising generated code.

Fortran numeric kinds, integer overflow, and floating-point rounding are not
fully preserved. A successful numerical comparison at one problem size does
not establish equivalence for every value or kind.

## Enumerators

`ENUM, BIND(C)` declares integer constants, not a separate Python enum class:

```fortran
enum, bind(c)
   enumerator :: red, green, blue = 10, next_color
end enum
```

The values are `red = 0`, `green = 1`, `blue = 10`, and `next_color = 11`.
Generated bindings use `Final[int]`, like ordinary integer parameters; Python
does not enforce their immutability. Numbering restarts for each enumeration,
and omitted values increment the preceding enumerator even after a negative
explicit value. This supports ordinary scopes and module visibility, not C ABI
bindings or newer named enumeration types. Renamed `USE` imports and duplicate
names in different flattened modules remain explicitly restricted.

## Branches and loops

```fortran
if (x > 0) then
   y = x
else
   y = -x
end if

do i = 1, n
   print *, i
end do
```

```python
if x > 0:
    y = x
else:
    y = -x

for i in range(1, n + 1):
    print(i)
```

Fortran DO upper bounds are inclusive. A descending loop such as
`do i = n, 1, -1` corresponds to `range(n, 0, -1)`. General dynamic-step
loops need a sign-aware stopping bound. Loop bounds are evaluated on entry;
their expressions must not be reevaluated after each iteration.

`EXIT` and `CYCLE` roughly correspond to `break` and `continue`. Named-loop
control may need generated machinery to reach an enclosing loop rather than
the innermost loop. Also preserve the Fortran DO variable's value after normal
completion, `EXIT`, or zero iterations: it need not equal Python's last yielded
value, and a zero-iteration Python loop does not create its target variable.

Fortran `SELECT CASE` can become conditional branches. Supported `DO CONCURRENT`
forms do not imply parallel Python execution. Python indentation replaces
Fortran's block-ending statements; declarations alone are not executable work.

## Array indices and lower bounds

Fortran arrays normally start at one; NumPy arrays start at zero:

```fortran
real :: a(3,4)
x = a(2,3)
```

```python
x = a[1, 2]
```

Fortran can declare other lower bounds:

```fortran
real :: b(-2:2,0:3)
x = b(-1,2)
```

```python
x = b[1, 2]  # (-1)-(-2), 2-0
```

The Python shape is still `(5, 4)`. Lower bounds belong to the Fortran entity,
not merely its NumPy data. Generated index calculations account for declared
bounds; allocation, pointers, and dummy arguments introduce additional rules.

Allocatable array dummies retain the actual allocation's lower and upper
bounds. Generated allocation records these bounds using runtime metadata;
`MOVE_ALLOC` transfers the same array object and its bounds. Reallocation in
an output/inout dummy returns the replacement and its bounds to the caller.
In contrast, an ordinary assumed-shape dummy `x(:)` starts at one, while
`x(0:)` starts at zero, regardless of the actual's lower bound. Indexing,
bound inquiries, and whole-array assignment use this association's bounds.
Shape-preserving assignment retains the allocation bounds; replacement by an
array expression with a different shape acquires one-based bounds. Empty
dimensions report lower bound one and upper bound zero.
These rules cover allocatable arrays; supported pointer associations also retain
pointer-specific bounds, including through pointer dummy arguments. Rank-changing
pointer remapping and non-default allocated component bounds remain limitations.
Do not copy an offset from one entity blindly to another.

A Fortran out-of-bounds negative subscript is not legitimate Python negative
indexing. For example, `a(0)` is invalid for `a(1:3)`; mapping it to `a[-1]`
would incorrectly select the last element. Bounds-check the original Fortran
when validating translations; not every emitted access checks bounds.

## Inclusive sections and strides

For an array whose lower bound is one:

| Fortran section | Simplified NumPy section |
| --- | --- |
| `a(:)` | `a[:]` |
| `a(2:4)` | `a[1:4]` |
| `a(1:5:2)` | `a[0:5:2]` |
| `a(5:1:-1)` | `a[4::-1]` |
| `a(:,2)` | `a[:,1]` |

Fortran includes the final bound; Python excludes it. Descending sections,
empty sections, omitted bounds, and nondefault lower bounds require care.
In particular, Fortran's omitted bounds do not automatically switch ends for
a negative stride as NumPy's do. The translator uses `_f_section_slice` for
strided sections instead of relying on a blanket index adjustment.

Scalar subscripts drop dimensions; sections and vector subscripts retain them.
For a matrix, `a(:,2)` is a vector, while `a(:,2:2)` is a matrix with one column.

## Multiple vector subscripts: Cartesian, not paired

This distinction is essential. Given `integer :: a(3,4)`:

```fortran
print *, a([1,3],[2,4])
```

Fortran selects **all combinations** of rows 1 and 3 with columns 2 and 4,
forming a `(2,2)` array. This is the NumPy equivalent:

```python
selection = a[np.ix_([0, 2], [1, 3])]
```

By contrast, `a[[0,2], [1,3]]` selects only two paired elements.
Vectors need not have equal lengths, and a read must preserve their order and
repetitions. Printing the Fortran selection traverses its first dimension
fastest, so its element order is `(1,2), (3,2), (1,4), (3,4)`.

Mixtures of vectors, slices, and scalars must also preserve dimension order.
Generated code uses an index tuple from `_f_array_indices`, for example:

```python
from fortran_py_runtime import _f_array_indices

# Fortran a([1,3],2:4), with lower bounds one:
selected = a[_f_array_indices(a, np.array([0, 2]), slice(1, 4))]
```

The helper is used for assignment as well as reading. Updating a copied
advanced-index selection does not update the original array:

```python
rows, columns = np.array([0, 2]), np.array([1, 3])
a[np.ix_(rows, columns)] = 7  # Writes back to a.
```

Repeated vector indices can be meaningful on reads, but a repeated selected
element is not a valid definable Fortran vector-subscripted assignment target.
Do not assume NumPy's behavior makes such Fortran assignments valid. Fortran
also restricts vector-subscripted actual arguments passed to procedures that
define their dummy arguments.

## Array order, constructors, and reshaping

Fortran array element order is column-major: the first subscript varies fastest.
NumPy's default reshape and flatten order is row-major.

```fortran
a = reshape([1,2,3,4,5,6], [2,3])
```

```python
a = np.array([1, 2, 3, 4, 5, 6]).reshape((2, 3), order="F")
# [[1, 3, 5],
#  [2, 4, 6]]
```

Generated `RESHAPE` calls use `_f_reshape`, which also implements `PAD` and
`ORDER`; simply adding `order="F"` is not enough for all those forms. Use
`a.ravel(order="F")` when reproducing Fortran element traversal, including
list-directed output and packing. Logical element order and physical
contiguity are separate: equivalent values do not require every NumPy array
to be stored in Fortran-contiguous memory.

Fortran array constructor elements may include arrays, whose elements are
concatenated in array-element order. Do not automatically replace every such
constructor with a nested Python list or a multidimensional `np.array`.

## Assignment, views, allocation, and pointers

Fortran intrinsic assignment copies values; Python `b = a` normally aliases
an ndarray. A simplified equivalent of independent array assignment is:

```python
b = a.copy()
```

Generated code uses `_f_assign_array` where needed to handle scalar expansion,
array values, and independent copies, including object-valued arrays. Basic
NumPy sections are views; vector-indexed selections are copies. Indexed
assignment must write through the index expression, not through a copied value.

| Fortran construct | Translation consideration |
| --- | --- |
| `allocate(a(n))` | Create array storage; ordinary Fortran allocation does not initialize values. |
| `allocate(b, source=a)` | Allocate using the source's values, with independent storage. |
| `allocate(b, mold=a)` | Use the model's type and shape, not its values. |
| `deallocate(a)` | Remove the allocated value; generated code commonly uses `None`. |
| `call move_alloc(a,b)` | Transfer the allocation and leave `a` unallocated, rather than copy elements. |
| `p => a` | Pointer association, not intrinsic value assignment. |

Allocation uses helpers such as `_f_allocate`; supported `MOVE_ALLOC` calls
update both bindings. Reading uninitialized Fortran storage is not made valid
by whatever initial values a translation happens to supply.

Pointer and TARGET assignments may need in-place updates to preserve aliases.
`ASSOCIATED(p)` tests whether the translated pointer has storage.
`ASSOCIATED(p, target)` checks storage identity, shape, and element strides,
not equal values or merely overlapping storage. Whole arrays, basic sections,
scalar array elements, boxed scalar targets, and pointer components are
supported. Scalar element associations retain writable views. Empty array
targets give false for the two-argument inquiry, even when `ASSOCIATED(p)` is
true. Unboxed Python scalar values are diagnosed rather than compared by value.
Same-rank lower-bound association such as `p(0:) => a(2:4)` is supported,
including strided sections and pointer components. Each pointer gets an independent
view and bounds metadata, so associating `q(-1:)` with the same target does not
change `p`'s bounds. Whole targets retain their bounds; sections default to one
unless explicit pointer lower bounds are supplied. Bounds inquiries, subscripts,
and writes through the pointer use those bounds. Rank-changing remapping such as
`p(1:2,1:3) => a` is explicitly rejected. Scalar non-pointer components without
preserved storage remain limited; this is not a complete pointer descriptor model.
Python references are not a general implementation of Fortran pointer
descriptors. Likewise, `IS_CONTIGUOUS` and `CONTIGUOUS` dummy arguments require
more care than testing one ndarray flag; consult the README's limitations.

## Masks and elementwise logic

```fortran
where (a < 0) a = 0
```

```python
a[a < 0] = 0
```

That is an idiomatic equivalent of this simple case. Generated `WHERE` code
uses operations such as `np.where(mask, new_values, old_values)` and assignment
helpers. The controlling mask is copied on entry and retained across the
construct's assignments, even if the original logical array or values used
to form it change. ELSEWHERE excludes previously matched elements; a masked
ELSEWHERE evaluates its new condition when that branch is reached. Nested
constructs remain restricted by their saved parent mask.

Named WHERE constructs and both `ELSEWHERE` and `ELSE WHERE` spellings are
supported, including names on branch/end statements. Mismatched names and
unmatched branch/end statements are diagnosed. Scalar logical assignments
inside WHERE are masked too, rather than updating the whole destination array.
An arbitrary sequence of reevaluated Python conditions is not equivalent.

For scalar logic, `.and.`, `.or.`, and `.not.` resemble `and`, `or`, and `not`.
For NumPy arrays, use `np.logical_and`, `np.logical_or`, and `np.logical_not`,
or suitably parenthesized `&`, `|`, and `~` on Boolean arrays. Python's scalar
operators cannot test the truth of a multi-element ndarray.

Fortran does not guarantee Python-style short-circuit evaluation of logical
operands. Do not rely on a logical operand to guard an unsafe array access.

`MERGE(tsource,fsource,mask)` is an elemental selection, not a scalar Python
conditional expression when any argument is an array. The runtime `merge`
helper supports scalar expansion and checks array conformability; general
NumPy broadcasting is not a substitute for Fortran conformability rules.

### FORALL is not a sequential loop

```fortran
forall (i=2:8)
   a(i) = a(i-1)
end forall
```

Unlike an ordinary `DO`, this assignment reads the original values before any
destinations are updated. With `a=[1,2,3,4,5,6,7,8]`, it produces
`[1,1,2,3,4,5,6,7]`, not eight ones.

The translation freezes the triplet ranges and mask, gathers copies of each
assignment's values and destination selectors, then applies that assignment.
A subsequent assignment in the same block sees the completed earlier
assignment, but uses the original controlling mask. Fresh Python index names
preserve variables outside the construct. Multiple indices, descending steps,
empty ranges and array-section assignments are supported. These temporary
lists can use significant memory for large iteration spaces.

Nested FORALL/WHERE bodies and pointer assignments are not yet supported and
are diagnosed explicitly. Ordinary `DO` loops retain sequential behavior;
`DO CONCURRENT` is a distinct construct, not given FORALL snapshot semantics.

### ASSOCIATE selectors: aliases versus expression values

```fortran
associate (a => x%v(2:4:2))
   a = a * 10
end associate
```

For numeric array components and basic sections, the translation retains a
NumPy view and assigns through it in place. This updates the selected elements
of `x%v`, rather than replacing the Python association name with a new array.
Scalar array elements use a zero-dimensional view. Component element types
and declared bounds are used when translating indexing and integer conversion.

An expression selector such as `a => x%v * 2` is different: its value is copied
on entry, so subsequent changes to `x%v` do not change `a`. Simple array-valued
arithmetic selectors retain metadata needed for indexing the temporary value.
All selectors are evaluated in the enclosing scope before binding associate
names. Shadowed bindings and their metadata are restored at `END ASSOCIATE`.

This is not complete association support. Whole derived-type/scalar-component
aliases, vector-subscripted selectors, pointer reassociation and scalar aliases
passed to procedures with rewritten output arguments still need manual review.

## Functions, subroutines, and arguments

```fortran
pure function square(x) result(y)
   real, intent(in) :: x
   real :: y
   y = x*x
end function square
```

```python
def square(x):
    return x * x
```

Python does not enforce Fortran `PURE`, `INTENT`, or declaration constraints.
A function's result variable becomes a returned value. A scalar subroutine
output cannot update the caller merely by rebinding a local Python parameter:

```fortran
subroutine increment(x)
   real, intent(inout) :: x
   x = x + 1
end subroutine increment
! Caller: call increment(x)
```

```python
def increment(x):
    return x + 1

x = increment(x)
```

The translator returns output dummy values and rewrites callers to receive
them; multiple outputs can require tuple unpacking. Scalar subroutine dummies
without `INTENT` are also returned when assignments, input statements, or
ordinary calls to known subroutines define them. This inference propagates
through call chains, including forward references and keyword arguments.
Read-only scalars are not returned, so expressions remain valid actual
arguments for them. Modified scalars require assignable actuals; output values
are copied back even on an early `RETURN`. Assumed-length scalar character
assignment preserves the actual argument's length.

Ordinary functions may modify scalar dummy arguments too. Such translations
return a tuple containing the function result followed by the modified dummies.
Generated call sites unpack the scalar updates while yielding the original
function result to the surrounding expression. Inline sequencing keeps the call
inside its condition or loop test and evaluates it once; array-element and
component destinations are captured before the call. This changes the Python
calling convention when invoking such a translated function manually. Calls
through procedure arguments or type-bound dispatch need manual review.

`VALUE` dummies are an exception: modifying one changes only the procedure's
local copy, never the caller's actual argument. They are excluded from
copy-back, and derived-type values are copied on entry so component assignments
also remain local. A procedure with both `VALUE` and ordinary modified dummies
copies back only the latter. Expressions are valid actuals for `VALUE` dummies.

An `ALLOCATABLE, INTENT(OUT)` dummy is automatically deallocated on procedure
entry. Its translation starts with `None`, so `ALLOCATED` is false before any
body statements execute. Returning without reallocating leaves the caller's
actual unallocated; allocating or assigning a new value in the procedure
returns that replacement to the caller. `INTENT(INOUT)` retains the incoming
allocation. This applies to both functions and subroutines.
For optional allocatable dummies, argument presence is tracked independently
of allocation, with or without `INTENT`: an explicitly passed unallocated
actual is present, while an omitted argument is absent. Allocation,
deallocation, and the `INTENT(OUT)` entry reset do not change `PRESENT`.
Generated optional allocatable defaults use a private omission sentinel rather
than `None`, which represents an unallocated but present actual. Forwarding
an absent dummy to another optional allocatable dummy preserves its absence.

This is not a complete alias or side-effect analysis: writes through unknown
procedures and complicated argument aliasing need manual review. Array and derived-type
arguments also need appropriate value, mutation, and copying behavior.
Preserve both generated procedure signatures and calling conventions when
editing a translation.

Supported OPTIONAL arguments use a missing-value representation such as
`None`, and `PRESENT` tests presence. Keyword calls retain argument names.
An elemental function applies a scalar calculation across conformable array
arguments; it is not permission for arbitrary NumPy broadcasting. Elemental
subroutines can use `_f_elemental_subroutine` for per-element execution and
output writeback, including impure routines with side effects.

## Modules, host association, and persistent locals

Fortran `USE` is not merely textual inclusion. Translated modules introduce
Python definitions and state; same-source programs can share mutable module
variables. Cross-file mutable state and renamed imports have explicit
restrictions. The batch tool's `--group` supplies dependencies in order but
does not discover them automatically.

Within one translation unit, procedures and generic interfaces that share a
name across modules receive distinct generated names, such as
`xf2p_strings_mod_helper`. Calls follow module-local, host, and `USE`
association, including `ONLY`, procedure renames, and re-exports. Local variables
and internal procedures shadow imported names. Type-bound member names remain
unchanged even when their implementation is qualified. Referencing an ambiguous
imported procedure is diagnosed rather than resolved arbitrarily.
Unambiguous definitions keep their original names. This does not provide
separate namespaces for same-named module variables or derived types.
Importing a qualified procedure across separately generated Python files is
currently diagnosed; combine the Fortran modules and program into one input
file to use this resolution path.

Named generic interfaces dispatch on numeric kind as well as element type and
rank. Translated calls carry kind metadata for numeric literals (including
`D` exponents and kind suffixes), declared scalars/arrays, array sections,
ordinary numeric arithmetic, and known function results. Named kind parameters
and keyword arguments are supported. Empty arrays use their dtype to identify
the element type. If numeric kind information cannot be determined, the call
raises an explicit error instead of silently selecting the first specific.
This dispatch metadata does not change the translator's general numeric
storage/precision model; it is not full emulation of every Fortran kind.
Direct calls to a generated generic from Python use NumPy dtype kinds, or kind
4 for ordinary Python numeric scalars without metadata.

Internal procedures can become nested Python functions. Host-variable writes
may require `nonlocal`; module-variable writes may require `global`. A local
declaration that shadows a host name must remain independent of it.

Fortran `SAVE`, initialized procedure locals, and supported DATA initialization
can retain state between calls. Initializing a Python local on every call is
not equivalent. The translator supplies persistent storage for supported
cases; moving its initialization into a function body can break that behavior.
Supported whole-array DATA initialization follows column-major element order.
Partial DATA objects and implied-DO DATA forms remain explicitly restricted.

## Derived types and character values

Fortran `value%component` becomes Python attribute access, `value.component`.
Derived types may be represented by generated dataclasses. Intrinsic
derived-type assignment must copy value components appropriately; assigning
the same Python object to two names is not generally equivalent. Pointer
components have distinct association semantics.

For supported `TYPE, EXTENDS(base)` declarations, the generated dataclass
contains one parent object. Inherited-component properties forward to it, so
`value%id` and `value%base%id` refer to the same storage, not independent copies.
Assigning/copying the parent component excludes extension fields. Multi-level
extension, parent-value and inherited-component constructors, and explicit
inherited/overridden procedure bindings have focused tests. This does not add
general polymorphic allocation or `SELECT TYPE`, parameterized derived types,
deferred/generic bindings, or finalization support.

Fixed-length Fortran character assignment pads with spaces or truncates:

```fortran
character(len=5) :: label
label = 'abc'
```

```python
label = "abc".ljust(5)[:5]  # "abc  "
```

Generated assignments use `_f_str_assign` to handle fixed lengths, including
arrays. `LEN` counts declared padding; `LEN_TRIM` excludes trailing spaces.
The legacy declarations `CHARACTER*3` and `CHARACTER*(3)` use the same
padding/truncation rules as `CHARACTER(LEN=3)`. Parenthesized lengths can
contain constant expressions, and `CHARACTER*(*)` dummy arguments retain
the actual argument's length, like `CHARACTER(LEN=*)`. Prefer the modern
`CHARACTER(LEN=...)` spelling in new Fortran code.
`TRIM` removes trailing spaces, not arbitrary whitespace: `.strip()` would
also remove leading blanks and is not equivalent.

Fortran character comparisons blank-pad the shorter operand; Python string
comparisons do not. Fortran `//` means concatenation, not Python floor division.
Supported deferred-length allocatable scalar assignment acquires the RHS
length; deferred-length character array and pointer assignment remain limited.

## Intrinsics: direct operations versus helpers

These are mathematical equivalents or the helpers used by the translator,
not a guarantee that every argument combination or context is supported.

| Fortran operation | Python/NumPy equivalent or emitted helper |
| --- | --- |
| `sin(x)`, `exp(x)`, `sqrt(x)` | NumPy elementwise mathematical functions. |
| `sum(a)` | `np.sum(a)`. |
| `sum(a,dim=1)` | `np.sum(a,axis=0)`; Fortran DIM numbering starts at one. |
| `product(a,dim=...)` | `_f_product`, including supported masks. |
| `size(a)`, `shape(a)`, `rank(a)` | `_f_size`, `_f_shape`, `_f_rank`, or a rank known from declarations. |
| `transpose(a)` | `np.transpose(a)` for a matrix. |
| `matmul(a,b)` | Runtime `matmul`, including special logical-array semantics. |
| `dot_product(a,b)` | `_f_dot_product`; conjugates the first complex vector, like `np.vdot`, not `np.dot`. |
| `pack`, `unpack`, `spread` | Runtime helpers preserving Fortran element order and shape rules. |
| `minloc`, `maxloc`, `findloc` | Runtime helpers for DIM, MASK, BACK, empty results, and one-based locations. |
| `cshift`, `eoshift` | `_f_cshift`, `_f_eoshift`. |
| Selected special functions | SciPy functions, imported only when needed. |
| `selected_int_kind`, `selected_real_kind`, `selected_logical_kind` | Runtime selection helpers, including keyword arguments and failure codes. |
| `kind(x)` | Static type/kind metadata; the inquiry does not evaluate `x`. |

Fortran reductions with MASK and DIM, logical matrix products, and location
intrinsics should not be replaced blindly with the nearest NumPy spelling.
For example, `np.argmin` returns a zero-based index and has different empty
array and multidimensional-result rules from `MINLOC`.

Kind selection uses the translator's kind-to-byte convention: INTEGER and
LOGICAL kinds 1, 2, 4, 8 and IEEE REAL kinds 4, 8 (decimal precision/range
6/37 and 15/307). Unsupported requests return failure codes, including -5
for a nonbinary real radix. This describes the translated runtime, not the
installed Fortran compiler: extended integer/real/logical kinds may differ.
Selection does not add kind-dependent storage or arithmetic emulation; existing
floating-point kind fidelity limitations still apply. Other intrinsics, such
as `SELECTED_CHAR_KIND`, remain unimplemented.

`BIT_SIZE(i)` uses the argument's declared Fortran integer kind, not the width
of its translated Python/NumPy storage. Kinds 1, 2, 4, 8, and 16 report 8,
16, 32, 64, and 128 bits. Supported literals, integer expressions, array
elements, components, and functions with known result declarations are modeled
without evaluating the argument. The result retains the argument's integer kind
for nested inquiries and generic dispatch. Unknown/non-integer argument models
and unsupported integer kinds are diagnosed explicitly.

Declared integer kind 16 uses a signed 128-bit model for `HUGE`, `DIGITS`,
`RANGE` and `RADIX`: `2**127-1`, 127, 38 and 2 respectively. These inquiries
use Python integers, without requiring a NumPy int128 dtype or evaluating the
argument. This does not extend kind selection, implement 128-bit array storage,
or emulate overflow in arithmetic.

`KIND` handles integer, real, complex, logical and character literals and
declared variables, including arrays, elements, sections and components.
`DOUBLE PRECISION` and the `DOUBLE COMPLEX` extension are normalized to
`REAL(KIND=8)` and `COMPLEX(KIND=8)`, including typed function headers.
Intrinsic type declarations can omit `::` when no attributes or initialization
require it, for example `INTEGER(8) i,j`, `REAL a(-2:2)`, and
`CHARACTER*(3) text`. Type/kind selectors, array bounds and character lengths
retain the same meaning as in the corresponding declarations with `::`.
Arithmetic and supported intrinsic results (for example `MATMUL`, `DOT_PRODUCT`,
reductions and conversions with explicit KIND selectors), and functions with
known result declarations, retain their result-kind metadata. An inquiry can
therefore inspect an unallocated array or a side-effecting function result
without evaluating it. Unknown expression kinds produce a translation error
instead of a missing Python `kind` function or a guessed answer. Reporting a
declared kind, including extended kinds, does not emulate that kind's storage
or arithmetic precision. User procedures and arrays named `kind` are not
automatically treated as intrinsic inquiries.

## Output and validation

`CALL EXECUTE_COMMAND_LINE` supports synchronous execution (default WAIT or
`WAIT=.TRUE.`) through the platform shell, with inherited stdin/stdout/stderr.
`EXITSTAT` receives a completed shell command's exit code; `CMDSTAT` is zero
for completed commands, including nonzero exits. A shell-launch failure gives
nonzero `CMDSTAT` and assigns/truncates/pads `CMDMSG`, without changing `EXITSTAT`.
If `CMDSTAT` is absent, a launch failure raises `RuntimeError`. On success,
`CMDMSG` remains unchanged. Status codes/messages are platform-dependent: the
runtime reports shell-launch failures as CMDSTAT=1 and does not separately
classify a shell's command-not-found exit code, unlike some compiler runtimes.
`WAIT=.FALSE.` is rejected; a dynamically false WAIT raises before launching.
Scalar output variables, components and array elements are supported, but
CMDMSG substring actuals are currently rejected. Commands run with the user's
permissions, so never execute untrusted translated programs.

`PRINT *, ...` becomes Python output machinery, including flattening arrays
in Fortran element order. Python may print logical values as `True` and `False`
rather than `T` and `F`. Formatting, whitespace, and default real precision can
differ even when the numerical result is acceptable.

Kind-suffixed logical literals such as `.TRUE._1` and `.FALSE._lk` become
Python Boolean values. Their kind metadata remains available to `KIND`
inquiries; text inside quoted strings is not rewritten.

Unlimited-repeat formats such as `(*(1X,I0))` consume the remaining output
items, including mixed scalars and arrays flattened in Fortran element order.
Supported groups can contain multiple data descriptors, nested finite repeats,
partial final cycles and `:` separator suppression. Each original output
expression is evaluated once. Code generation is limited to 128 data descriptors
per repeated group, with a clear error above that limit. This remains a limited
formatter, not a complete Fortran I/O implementation: fixed prefix descriptors
consuming array arguments and complex values requiring two real descriptors
are separate limitations.

List-directed complex output retains the `(real,imaginary)` notation, with
each component using Python's precision-preserving float representation rather
than a fixed decimal count. Numerical comparison checks components separately,
including scientific/Fortran D exponents and whitespace within the pair.
Standalone numeric-looking character output is indistinguishable from complex
output to the comparer; use `--diff-exact` when spelling matters. Explicit
formatted output still follows its supported edit descriptors.

A literal formatted `PRINT` without an output-item list still executes its
literal and control descriptors: `print "('hello')"` becomes `print('hello')`.
Supported literals, repeats, spacing and record breaks are preserved; `:` or
a data descriptor terminates processing when no items remain. An unsupported
descriptor in this itemless form is diagnosed rather than silently omitting
the statement.

For sequential formatted external I/O, integer `UNIT` and negative `NEWUNIT`
values resolve through a runtime table of Python file objects, shared across
procedures. Named and scratch files, `REWIND`, and `CLOSE` are supported.
External input supports numeric/logical list-directed reads and named scalar
character `'(a)'` reads, including `IOSTAT`/`IOMSG` handling. Other input formats,
direct/unformatted access, and advanced list-directed syntax remain unsupported;
this is not a complete emulation of Fortran records or file connections.

Formatted internal input can read fixed-width fields from a scalar character
record, for example:

```fortran
read(text, '(i4,1x,i2,1x,i2)') year, month, day
```

Literal formats support `I`, `F`, `E`, `D`, `G`, `L`, `A`, `nX` and flat repeats
such as `3I2`. Targets must be compatible scalars, array elements or scalar
components. Short records are padded with blanks; integer/real blank fields
become zero. Real fields without a decimal point use the format's implied
decimal places. Character fields preserve the target's declared length.
`IOSTAT`/`IOMSG` are supported for these formatted reads; error codes and message
text are not intended to reproduce a particular compiler's spelling.
Unsupported descriptors, format variables/labels, nested groups, format
reversion, whole-array targets and record changes produce an explicit error.
The older list-directed internal input path remains separate and does not
support `IOMSG`. It accepts comma/whitespace separators and quoted character
fields (including embedded separators and doubled quotes). Null values,
repeat syntax and slash termination are diagnosed rather than silently
discarded; quoted numeric input is rejected.

Validate against the original program:

```console
python xf2p.py example.f90 --run-diff
```

Use the README's comparison options for tolerances or normalized exact-text
comparison. Also compare generated files and other side effects where relevant:
stdout equality alone is not sufficient. For nondeterministic programs,
`--run-both` permits inspection without asserting equality.

## Unsupported constructs and manual revisions

Defined operators and defined assignment are diagnosed as unsupported;
ordinary named generic interfaces are a separate feature. GOTO control
transfers are rejected rather than silently discarded. Coarrays, general
polymorphism, finalization, and `SELECT RANK` are not generally supported.
Not every unsupported form has a translation-time diagnostic: always inspect
and execute the result before relying on it.

When polishing generated Python, preserve lower bounds, element order, copy
and alias relationships, persistent state, and procedure output conventions.
Keep `fortran_py_runtime.py` available and refresh older adjacent copies when
updating the translator. A shorter NumPy expression is an improvement only
if it retains the original Fortran semantics.
