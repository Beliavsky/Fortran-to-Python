Fortran-to-Python execution tests
================================

Run from the repository root:

    python -m pip install numpy scipy pytest
    pytest -q -rx

Local exploratory programs in cases/more/ are excluded by default. Include
them with pytest -q --include-exploratory; unsupported translations and genuine
output mismatches still fail normally. cases/stash/ is always excluded.
For one exploratory case, for example:
    pytest -q --include-exploratory tests/test_xf2p_execution.py -k test18_move_alloc

Requirements: Python, NumPy, pytest, and gfortran on PATH. Execution tests
skip explicitly if gfortran or NumPy is missing; they do not pretend to pass.
SciPy is optional for the translator/runtime and ordinary translated programs;
special-function programs require it. The math_intrinsics and
modern_math_intrinsics execution comparisons
and SciPy-specific unit test skip explicitly when SciPy is unavailable.
Each subprocess has a 90-second timeout. Compiler commands use argument lists,
so Windows paths with spaces work without shell quoting.

internal_formatted_read checks fixed-width internal input against gfortran,
including date fields, implied decimals/exponents, logical/character fields,
record padding and IOSTAT/IOMSG errors. test_internal_formatted_read.py also
checks scalar components/elements and explicit unsupported-format diagnostics.

Corpus (48 programs)
--------------------
handwritten/: 18 small deterministic programs exercising scalars, loops,
branches, SELECT CASE, arrays, masks, matrices, procedures, modules, strings,
allocation, and formatted file I/O.

features/: 26 focused programs covering OPTIONAL/PRESENT, keyword calls,
explicit SAVE, EXIT, EQV/NEQV, elemental and impure elemental procedures,
DO CONCURRENT, derived-type assignment/arguments/results, type extension,
type-bound procedures, labeled FORMAT, selected-kind intrinsics, and a
controlled EXECUTE_COMMAND_LINE call. See FEATURE_COVERAGE.txt for results.
array_component_initializers also verifies default component values and
independent storage between objects and between derived-type array elements.
data_initializers verifies DATA scalars, whole arrays in column-major order,
literal repeat counts, character padding/truncation, and implicit SAVE of local
scalar/array values across calls. Partial objects, implied-DOs, named repeat
counts, mixed array/scalar groups, and unsupported DATA contexts are diagnosed
explicitly rather than discarded. DATA does not execute as an assignment.
derived_scalar_initializers checks constructor and named-value initializers,
independent derived-object storage, keyword constructors, and implicit SAVE
of initialized derived scalars in functions and subroutines.
nested_sum_dimensions checks dimensional and masked SUM inside other calls,
nested reductions, and the column standard-deviation expression using SPREAD.
Already-lowered NumPy axes must survive recursive expression translation.
merge_shapes tests elemental MERGE with scalar masks/sources, both source
orders, higher-rank and empty arrays, and logical/complex/character values.
Array arguments must conform; NumPy's extra broadcasting is not accepted.
location_intrinsics verifies MINLOC/MAXLOC/FINDLOC, DIM, MASK, BACK, KIND,
Fortran array-element order, empty arrays, and character/logical searches.
host_association checks host counter updates, module globals, an internal
procedure accessing its parent's dummy argument, array bounds and CHARACTER
metadata, functions, and local-variable shadowing. log10_values tests scalar
and elemental LOG10 without needing SciPy.
tan_values tests scalar and elemental TAN, positive/negative arguments,
and preservation of mathematical names inside printed labels, using NumPy.
modern_math_intrinsics preserves the user's xintrinsics.f90 and compares all
printed mathematical results. floating_intrinsics adds arrays, signed inputs,
zero/subnormal neighbors, model spacing, and two-argument ATAN checks.
math_intrinsics preserves the user's xintrinsics_all.f90 checker counters
and internal procedures, exercising all 73 original checks. Its
Fortran reference uses -O3: the local MinGW compiler/library combination lacks
the runtime sinpi symbol used at -O0 for the constant elemental test vector.
All other reference programs continue to use -O0. The generated Python still
evaluates its array expressions at runtime.

stash/: manual probes retained for reference; excluded from automated discovery.

existing/xsum_dim_int.f90: copied from C:\python\fortran\xsum_dim_int.f90
on 2026-10-04; only line-ending differences. Tests integer kinds and axis sums.

roundtrip/: three original Python programs and their fixed xp2f-generated
Fortran snapshots. These are self-contained (no python_mod or LAPACK).
Generated with C:\python\Python-to-Fortran\xp2f.py at Git HEAD
1769bfa086645218454eaa625349f14eebb157ca on 2026-10-04.
The tests do not invoke or require xp2f.py. Keep these snapshots stable;
regenerating them should be a separate, reviewed integration step.

Method
------
Compile and execute the original Fortran with -O0 -g -fcheck=all -fbacktrace.
Translate with the repository's xf2p.py into pytest's temporary directory,
then execute the resulting Python and compare stdout tokens.
Round-trip cases additionally execute the original Python and compare its
output against the Fortran reference before testing xf2p.py.

Ignore whitespace, but require equal token counts and textual labels.
Standalone logical tokens T/True and F/False are equivalent, matching the
CLI's --run-diff behavior; opposite logical values still fail comparison.
Integer tokens are compared exactly; real tokens use relative tolerance
1e-9 and absolute tolerance 1e-11, accepting Fortran D exponents.
Standalone complex pairs are tokenized as one value, accepting internal spaces
and line wrapping, then compared component-wise at the same tolerances.
Execution tests now use the shared CLI/batch comparer; matching NaNs and
same-sign infinities also compare equal. Character output that looks like a
logical/numeric value cannot be distinguished here; exact-text CLI comparison
is available when its spelling matters.
This is numerical-output validation, not byte-for-byte formatting validation.
Original Fortran and translated Python run in separate directories, so file
I/O cannot accidentally reuse files produced by the reference execution.

Expected-failure handling
-------------------------
There are currently no entries in the established suite's KNOWN_FAILURES map.
The mechanism remains available for explicitly confirmed failures: references
must still compile and execute successfully; strict unexpected success forces
removal of obsolete expectations. Other assertion failures inside a known-
failing translation may also count as expected failures, so inspect tracebacks.

To investigate without expected-failure masking:

    pytest -q --runxfail tests\test_xf2p_execution.py

To save machine-readable test results:

    pytest -q -rx --junitxml=reports\pytest.xml

The suite is a starting corpus, not a complete support guarantee. Larger
integration programs, helper-dependent p2f output, random-number algorithms,
more complex-number and derived-type cases, and additional unsupported syntax need
dedicated tests in subsequent expansions.

Fixed on 2026-10-04: integer whole-array, section, and WHERE assignments
convert elementwise with np.asarray(..., dtype=int), while scalar variables
and individual elements retain scalar int() conversion. The logical_masks
case now passes. integer_assignment_conversions checks positive/negative real
truncation, scalar expansion, vector/matrix sections, elements, and WHERE.

Also fixed on 2026-10-04: strided sections on expression and assignment paths,
including WHERE and single-line IF assignments. strided_sections checks
positive/negative/dynamic strides, omitted bounds, empty sections, non-unit
declared lower bounds, multiple dimensions, nested bounds, and overlapping
assignment. Unlike Python, Fortran's omitted bounds do not reverse with a
negative stride. Runtime triplet conversion rejects zero strides and selected
out-of-bounds elements. The original array_sections case now passes.

Also fixed on 2026-10-04: TRANSPOSE and DOT_PRODUCT translation, and intrinsic
keyword arguments for TRANSPOSE, MATMUL, DOT_PRODUCT, and RESHAPE. Complex
DOT_PRODUCT conjugates its first vector; logical DOT_PRODUCT uses ANY of AND,
and logical MATMUL uses AND/OR rather than numeric sums. Three new programs
check integer, complex, and logical matrix/vector operations.

Fixing TRANSPOSE exposed a wrong-result RESHAPE bug in matrix_operations:
Fortran source elements must fill in column-major order. Translation now uses
a dedicated helper implementing Fortran ordering, PAD, and ORDER, without
changing ordinary NumPy reshape defaults. The original matrix case now passes.

Also fixed on 2026-10-04: missing fixed-length string assignment, LEN_TRIM,
ADJUSTL, and INDEX helpers. Assignment pads/truncates scalars and arrays;
LEN_TRIM and ADJUSTL operate elementwise and treat only spaces as blanks.
INDEX uses one-based positions, zero for no match, optional BACK, and
broadcasting. The string_assignment program verifies scalar/array assignment,
initializers, zero length, padding, truncation, and search; strings now passes.
Substring reads are covered by strings; substring writes and deferred-length
allocatable strings are not yet covered by these regressions.

Also fixed on 2026-10-04: ISO_FORTRAN_ENV kind imports with or without
INTRINSIC/ONLY and with renamed imports. NON_INTRINSIC modules are not treated
as the built-in module. The existing xsum_dim_int case and new iso_kind_imports
case both pass, including module and procedure-local aliases.
Kind-number values use the existing GNU-style convention (1/2/4/8 for integer
storage sizes). They are not portable processor-independent kind identifiers.
Resolving these constants does not yet guarantee exact kind-sized integer
storage or overflow semantics throughout translated Python/NumPy operations.

Also fixed on 2026-10-04: type-bound calls no longer disappear. Derived types
emit forwarding methods for explicit procedure bindings, including renamed
bindings, default/named PASS, NOPASS, optional arguments, function results,
and explicit scalar OUT arguments. CLASS(type) dummies retain derived-type
metadata. CONTAINS inside a type is distinguished from the enclosing unit's
CONTAINS. The expanded type_bound_procedure case checks nested objects and
calls from one bound procedure to another as well as ordinary component-array
indexing. Unsupported/unresolved CALL statements fail explicitly rather than
being silently discarded. Deferred/generic bindings and indexed-object calls
are not yet supported by this implementation. Parent components are covered by
the later type-extension fix below.

Also fixed on 2026-10-04: explicit-shape array-component initialization in
derived types. Factories preserve initial values, shape, element type, scalar
expansion, and CHARACTER padding/truncation. Derived-type array components
construct default elements or copy explicit initializers independently, so
mutating one element/object does not modify siblings, other instances, or the
initializer. Uninitialized intrinsic arrays remain np.empty; allocatable and
pointer components keep their existing unallocated/disassociated behavior.
Complex scalar and vector initialization are tested. Complex-pair literals
nested inside array constructors and chained component-array indexing were
fixed in the follow-up described below.

Also fixed on 2026-10-04: complex literals within untyped/typed array
constructors, complex arithmetic and nested calls, and keyword constructor
arguments. Parenthesized argument lists and strings are not complex literals.
Chained component-array reads and writes now retain every subscript, including
matrix indices, sections/strides, integer conversion, and masked assignments.
Component bounds are taken from the component declaration, not its root
object's array bounds. The expanded array_component_initializers regression
checks non-default bounds for both components and arrays of derived objects.
Indexed-object bound CALLs and general inheritance remain outside this fix.

Also fixed on 2026-10-04: ALLOCATE with SOURCE= and MOLD=. SOURCE copies
values into independent storage; MOLD supplies shape without copying values.
Explicit bounds, scalar SOURCE expansion, scalar allocation, multiple objects,
intrinsic element types, fixed-length CHARACTER, derived-type defaults/copies,
and default-bound allocatable components are covered by allocate_models.
Whole-array model bounds and explicit bounds are captured within the current
unit, so later changes to extent variables do not change allocated bounds.
Zero extents return LBOUND=1/UBOUND=0. STAT is zero on success and nonzero on
allocation errors; its numeric error codes and ERRMSG text are not intended
to duplicate a particular Fortran compiler. Existing allocation is retained
when an already-allocated object fails allocation with STAT.
Type-spec ALLOCATE, deferred-length CHARACTER, and non-default bounds for
allocated components remain unsupported with explicit diagnostics. General
cross-procedure preservation of allocatable-dummy bounds is not guaranteed.

Mathematical intrinsic dependencies
----------------------------------
Gamma, LOG_GAMMA, ERF, ERFC, ERFC_SCALED, and Bessel functions use scipy.special.
ERFC_SCALED maps to erfcx rather than exp(x*x)*erfc(x), avoiding intermediate
overflow for large positive x. Reference:
  https://docs.scipy.org/doc/scipy/reference/generated/scipy.special.erfcx.html
Only special-function programs import SciPy, and missing installations receive
an explicit 'python -m pip install scipy' message. NumPy/runtime helpers handle
hyperbolic functions, HYPOT, NORM2, degree/PI-scaled trigonometric functions,
and EPSILON. NORM2 supports DIM and scaled accumulation. PI-scaled helpers
reduce their arguments before multiplication and preserve exact cardinal values.
EPSILON reflects the translated value's dtype; the translator's existing
promotion of Fortran REAL declarations/literals to float64 remains a kind-
fidelity limitation outside the real64 regression used here.

Host association and LOG10
--------------------------
Program-internal procedures are nested Python functions sharing the main
invocation's bindings. Host names use nonlocal, module names use global, and
explicit locals/dummy arguments shadow outer names. Host array/type/character
metadata is retained when translating expressions and assignments. The scalar
impure_elemental module-state test now passes; this does not establish a
general evaluation order for side-effecting elemental array calls.
The original xintrinsics_all.f90 needs no counter-argument workaround anymore.
LOG10 maps to NumPy for scalars and arrays and does not add a SciPy dependency;
mathematical names inside printed string labels are preserved.

CLI and batch output comparison
-------------------------------
xf2p.py --run-diff and xf2p_batch.py --run-diff share fortran_output_compare.py.
Defaults are --rtol 1e-9 --atol 1e-11 for standalone real numeric tokens;
integers and labels compare exactly. Fortran D exponents, whitespace/line
wrapping, and matching NaN/infinity spellings are handled. --diff-exact implies
--run-diff and uses exact normalized lines (the CLI's previous behavior), not
byte-for-byte whitespace equality. Mismatches return nonzero and identify the
first genuine mismatch, skipping preceding numerically equivalent tokens.
Only stdout is compared; stderr remains visible and process failures fail.
Standalone T/True and F/False tokens are equivalent in default comparisons;
generated Python keeps its idiomatic True/False output. Character output with
these standalone words is indistinguishable from logical output; --diff-exact
preserves spelling differences. Embedded labels such as flag=T remain exact.
--time-both also implies --run-diff. Use --run-both --time to time intentionally
different output (for example unreplayed random draws) without comparing it.
Invalid tolerances are rejected. tests/test_output_compare.py and
tests/test_xf2p_run_diff.py cover the shared comparator and all CLI execution
modes, options, exit codes, and batch forwarding. ULP-sensitive regression
checks remain exact rather than relying on this default tolerant comparison.

Floating-point decomposition and model inquiries
------------------------------------------------
FRACTION/EXPONENT and SCALE/SET_EXPONENT use binary decomposition and scaling.
NEAREST returns the adjacent representable value in the requested direction;
zero direction is rejected. SPACING is positive and clamped to TINY for zero
and subnormal inputs, rather than blindly using NumPy's spacing. RRSPACING
uses ABS(FRACTION(x))*2**DIGITS(x). Numeric model inquiries use the translated
dtype. Runtime tests cover binary32/binary64; general Fortran kind fidelity
remains the existing limitation described above. Nonfinite inputs whose
Fortran result is processor-dependent are not assigned a compatibility guarantee.
References:
  https://gcc.gnu.org/onlinedocs/gfortran/SPACING.html
  https://gcc.gnu.org/onlinedocs/gfortran/RRSPACING.html
  https://numpy.org/doc/stable/reference/generated/numpy.finfo.html

BLOCK lexical scope
-------------------
BLOCK locals use distinct generated names; nested and sibling blocks do not
overwrite enclosing variables. Automatic scalar/array storage and block
parameters are initialized at block entry, including inside loops with changing
array bounds. Strings, derived-type component names, and keyword argument names
are preserved. Tests cover program, subroutine, and module-function contexts,
host updates, and collisions with generated names.
BLOCK-local USE, SAVE/initialized nonparameter locals, and derived-type
definitions currently fail explicitly instead of being flattened incorrectly.

Named DO control flow
---------------------
EXIT/CYCLE resolve construct names case-insensitively. Transfers to the current
loop use break/continue; transfers across nested loops use a private control
exception caught by the target iteration. Only that private exception is caught.
Counted-loop normal termination still updates the DO variable; EXIT preserves
its current value. Counted DO, DO WHILE, and bare DO are covered, along with
multi-level transfers, blocks, SELECT CASE, empty loops, descending steps, and
reusing the translator. Unknown/mismatched construct names are rejected.
Named DO CONCURRENT remains explicitly unsupported.

USE-associated module state
---------------------------
For modules and programs in one input source, USE-associated variables retain
their module storage. Main-program assignments and updates in module/internal
procedures share that storage. ONLY lists and PUBLIC/PRIVATE accessibility are
respected; local procedure variables and BLOCK locals can shadow host variables.
Imported array types/bounds and CHARACTER lengths are retained without local
reinitialization. Repeated main calls do not reset module storage on entry.
Transitive USE associations and procedure-local USE statements are tested.

The CLI's multi-file --mode-program path still emits separate Python modules.
Mutable state imported across those files is rejected to avoid copying scalar
bindings by value; combine the module and program into one Fortran source for
this workflow. Renamed USE variables and duplicate mutable-variable names in
different flattened Fortran modules also fail explicitly pending namespace
support. These restrictions do not apply to ordinary procedure-only imports.

SHAPE and RANK inquiries
------------------------
SHAPE returns an integer extent vector in Fortran dimension order, including
an empty vector for a scalar and zero extents for empty arrays. SOURCE/KIND
keywords and positional KIND are supported. Default SHAPE uses integer kind 4;
explicit supported kinds are 1, 2, 4, and 8. RANK accepts A and returns zero for
scalars. Declared ranks are folded without evaluating storage, allowing RANK of
unallocated objects and rank-based specification expressions. Assumed-rank
arguments and array-section expressions use runtime rank inquiries.
The shape_rank fixture checks non-one-based bounds, sections, assumed-shape/rank
arguments, scalar/empty inquiries, allocation-independent ranks, and RESHAPE
ORDER. SELECT RANK is not yet supported and is rejected rather than executing
all branches. This inquiry support does not imply SELECT RANK support.

Elementwise logical expressions
------------------------------
tests/test_logical_expressions.py and features/elementwise_logical.f90 cover
.and., .or., and .not. on scalars and arrays, including mixed scalar/array
operands, multidimensional and empty arrays, compound comparisons, nested
function arguments, WHERE masks, and scalar IF conditions. The expression AST
lowers logical operations to np.logical_and/or/not, preserving comparison and
AND/OR/NOT precedence. Operator-looking text inside strings is left unchanged.
Both operands are evaluated; Fortran does not guarantee short-circuit
evaluation. Generated Python retains idiomatic True/False output.

Additional array, string, allocation, and bit intrinsics
------------------------------------------------------
tests/test_additional_intrinsics.py and features/additional_intrinsics.f90
exercise PRODUCT (DIM/MASK, positional logical MASK, empty reductions, numeric
types), UNPACK (Fortran element order, scalar/array FIELD), CSHIFT/EOSHIFT
(dimensions, scalar/array SHIFT and BOUNDARY, zero/large/negative shifts),
ADJUSTR, SCAN/VERIFY (BACK/KIND), REPEAT, and elemental bit operations BTEST,
IBSET/IBCLR/IBITS, IAND/IOR/IEOR, SHIFTL/SHIFTR. Bit operations use default
32-bit words or recognized integer declaration kinds/kind-suffixed I literals;
this does not solve general expression-result kind inference or kind fidelity.

features/move_alloc_contiguous.f90 checks MOVE_ALLOC, destination replacement,
source deallocation, bound transfer, later source reallocation, and unallocated
sources. MOVE_ALLOC currently requires named allocatable variables, not derived
components; general allocatable dummy ownership across procedure calls remains
limited. IS_CONTIGUOUS uses NumPy storage flags. Nonpointer, nonallocatable
CONTIGUOUS array dummies use temporaries for strided arguments, copying writable
temporaries back. This is not a complete emulation of Fortran array descriptors:
multidimensional inquiries can differ where NumPy storage order differs from
the original Fortran layout. Derived-type/pointer allocation semantics remain
partial.

COMMAND_ARGUMENT_COUNT and GET_COMMAND_ARGUMENT use sys.argv, including optional
VALUE/LENGTH/STATUS, fixed-length padding, truncation, and missing arguments.
Argument zero denotes the Python script rather than the original executable;
do not expect --run-diff to equate those program names.

Derived-type array components
----------------------------
tests/test_derived_type_arrays.py and features/derived_type_array_components.f90
cover independent object initialization, whole-array scalar-component assignment
and projection (including nested paths and WHERE masks), matrix shape and
Fortran element order, intrinsic assignment copies, saved arrays, and recursive
list-directed derived-type output. PACK accepts scalar masks and an optional
VECTOR and selects elements in Fortran order. These checks do not imply full
support for pointer components, defined I/O, or component projections through
arbitrary parent array sections. An array component of an unindexed array parent
is rejected; use explicit subscripts rather than creating two ranked parts.
Existing generated programs need a refreshed adjacent fortran_py_runtime.py.

Deferred-length character scalars
--------------------------------
tests/test_deferred_character.py and features/deferred_length_character.f90
cover whole-variable intrinsic assignment to CHARACTER(:), ALLOCATABLE scalars:
initial allocation, growing/shrinking and empty strings, trailing blanks,
fixed-length RHS values, concatenation, REPEAT, scalar derived components,
saved locals, BLOCK locals, function results, and deallocation/reassignment.
Fixed-length strings retain their padding/truncation rules. Deferred-length
character array and pointer assignments are not supported; the covered named
forms are rejected with a clear diagnostic. Explicit deferred-length ALLOCATE
and character substring assignment are not covered by this feature.

Impure elemental subroutines
---------------------------
tests/test_elemental_subroutines.py and features/impure_elemental_subroutines.f90
cover IMPURE/ELEMENTAL subroutine recognition, input-only side effects, scalar
input expansion, INTENT(OUT)/INTENT(INOUT) values, output-only calls, multiple
outputs, keyword arguments, matrices in Fortran element order, empty arrays,
and strided actuals. The runtime calls the scalar routine once per element and
copies outputs back into the original ndarray/view. Conformability is required;
NumPy's general broadcasting is not substituted for Fortran argument rules.
Refresh adjacent runtime copies when running newly generated translations.

Defined operation diagnostics
----------------------------
tests/test_defined_operations_diagnostics.py checks translation-time rejection
of INTERFACE OPERATOR(...) and INTERFACE ASSIGNMENT(=), including named operators,
continuations, explicit procedure interfaces, and type-bound GENERIC bindings.
Messages identify the operation and available procedure names. Declarations are
rejected even if unused; overload resolution is not implemented. CLI checks
verify a nonzero exit and no generated Python rather than a later runtime error.
Intrinsic operations and ordinary named generic interfaces remain supported.

Vector subscripts
-----------------
tests/test_vector_subscripts.py and features/vector_subscripts.f90 cover
Cartesian selection with multiple vector subscripts, mixtures of vectors,
scalars and slices, axis order, nondefault lower bounds, reversed sections,
empty and repeated vectors, indexed assignment and WHERE writeback.
Ordinary scalar/slice sections continue to share storage with their arrays.

Integer model kinds
-------------------
tests/test_integer_model_kinds.py and features/integer_model_kinds.f90 cover
HUGE, DIGITS, RANGE and RADIX using declared INTEGER kind metadata rather than
Python storage dtype. Coverage includes default and legacy declarations,
ISO_FORTRAN_ENV kinds and aliases, kind parameters, scalar/array arguments,
unallocated arrays, derived components, literal kinds, arithmetic, procedure
dummies and host/local scope. Model inquiries do not evaluate the integer value.
This uses the existing kind-to-byte convention for kinds 1, 2, 4 and 8; it is
not general integer-kind or overflow emulation. Unknown expression kinds and
REAL/COMPLEX model inquiries still use their translated NumPy storage dtype.

Complex output and comparison
-----------------------------
tests/test_complex_output.py and features/complex_output.f90 cover scalar and
array output, single/double precision, tiny and large components, signed zero,
nonfinite values, Fortran element order, and separation from character output.
tests/test_output_compare.py and tests/test_xf2p_run_diff.py cover tolerant
component-wise comparisons and the unchanged exact-text mode in CLI/batch runs.

Kind selection
--------------
tests/test_selected_kinds.py covers SELECTED_INT_KIND, SELECTED_REAL_KIND and
SELECTED_LOGICAL_KIND, keyword/optional arguments, nested calls, boundaries,
failure codes, and rejection of noninteger/nonscalar requests. The corresponding
feature programs and selected_kinds.f90 compare declarations and model inquiries
with native Fortran. These three cases are no longer expected failures.
Selection uses the translator's byte-kind convention: INTEGER/LOGICAL 1,2,4,8
and IEEE REAL 4,8. It is not a query of the installed compiler's extended kinds,
nor does it add exact kind-dependent arithmetic/storage emulation.

Derived-type extension
----------------------
tests/test_type_extension.py, features/type_extension.f90,
features/type_extension_components.f90 and features/type_extension_bindings.f90
cover inherited component access and explicit parent-component aliases, scalar
and array components, multi-level extension, independent assignment copies,
parent replacement, structure constructors, component-array projection, and
inherited/overridden procedure bindings. The parent is one contained object;
forwarding properties avoid duplicate storage. A parent-component copy has the
parent type and excludes extension fields. Unknown parents and redeclared
inherited fields are diagnosed. type_extension is no longer an expected failure.
This does not add general SELECT TYPE/polymorphic allocation, parameterized
derived types, deferred/generic bindings or finalization support.

Synchronous command execution
-----------------------------
tests/test_execute_command_line.py and features/execute_command_line.f90 plus
features/execute_command_status.f90 cover EXECUTE_COMMAND_LINE positional and
keyword arguments, default/synchronous WAIT, status outputs, unchanged messages
on success, launch failure with/without CMDSTAT, padding/truncation, array-element
and component outputs, host-variable updates, and output ordering. Launch errors
are simulated without depending on the installed shell being missing. Native
comparisons use portable echo/exit shell builtins. WAIT=.FALSE. and CMDMSG
substrings are explicitly rejected. A completed shell's nonzero exit, including
its command-not-found exit code, is reported through EXITSTAT; shell-launch
failures give CMDSTAT=1 or raise without CMDSTAT. Exact processor-specific
CMDSTAT codes/messages are not emulated. The former expected failure is removed.

Integer enumerators
-------------------
tests/test_enumerators.py and features/enumerators.f90 cover ENUM, BIND(C),
explicit and implicit values, zero-based resets, negative and repeated values,
integer arithmetic and array bounds, SELECT CASE, continuations, semicolons,
procedure/host/BLOCK scopes, PUBLIC/PRIVATE and USE ONLY visibility, model
inquiries, malformed declarations, and reused translator instances. ENUM is
lowered to ordinary INTEGER, PARAMETER declarations before scoping analysis;
generated Python uses Final[int], not Enum objects. This does not implement
C ABI bindings or newer named enumeration types. Renamed USE imports and
colliding names in different flattened modules have explicit diagnostics.

Sequential formatted file units
-------------------------------
tests/test_file_units.py and features/file_units.f90 cover integer UNIT and
negative NEWUNIT connections, shared procedure connections, scratch files,
named OLD/NEW/REPLACE/UNKNOWN files, append positioning, REWIND, CLOSE/DELETE,
list-directed numeric/logical input, whole arrays and sections in Fortran order,
character '(a)' reads, EOF, and OPEN/READ IOSTAT/IOMSG. formatted_file_io is no
longer an expected failure. Named files default to read/write access; explicit
ACTION is checked. Units 5/6/0 resolve to stdin/stdout/stderr when not otherwise
connected. Older generated file-object handles remain usable for output.

This does not implement full Fortran record or list-directed input semantics:
null/repeated values, slash termination, complex/character list input, direct
and unformatted access, other input formats and control specifiers remain
unsupported. Implicit fort.N file creation and reopening a connected unit
without CLOSE are not supported. Existing generated translations need a refreshed
adjacent fortran_py_runtime.py before using the new file helpers.

Extreme reductions
------------------
tests/test_extreme_reductions.py and features/extreme_reductions.f90 cover
numeric MAXVAL/MINVAL with positional and keyword DIM/MASK, positional-mask
overloads, dynamic dimensions, matrix and nested reductions, repeated lowering,
conformability, empty arrays/slices and all-false masks. Runtime helpers reject
nonlogical or nonconformable masks and invalid dimensions. Integer empty results
use declared kind metadata; ordinary results preserve the array's storage dtype.
REAL empty sentinels follow NumPy storage dtype; default REAL/kind fidelity
remains a limitation, rather than being implemented by this reduction fix.
CHARACTER MAXVAL/MINVAL are not implemented by these numeric runtime helpers.

Empty MAXVAL follows the documented -HUGE rule, including integer input:
https://gcc.gnu.org/onlinedocs/gfortran/MAXVAL.html
The local gfortran instead returns the most-negative integer for empty/masked
integer MAXVAL. Native comparisons check an explicit sentinel-range invariant
for those cases; runtime unit tests require exactly -HUGE. Other fixture outputs
are compared normally, including a selected most-negative integer. Infinities
have separate runtime tests.

inferred_scalar_outputs.f90 checks modified scalar dummies without INTENT,
forward and keyword CALL chains, early RETURN with SAVE, omitted optional
outputs, and assumed-length CHARACTER copy-back. Unit regressions are in
test_inferred_scalar_outputs.py.

function_scalar_outputs.f90 and test_function_scalar_outputs.py check scalar
copy-back from functions, including nested expressions, forward calls, early
RETURN, keyword/optional actuals, array elements, and reevaluated loop tests.

value_arguments.f90 and test_value_arguments.py check that VALUE dummies in
functions and subroutines are not copied back, including mixed VALUE/reference
arguments, expression actuals, and local copies of derived-type components.

allocatable_out.f90 and test_allocatable_out.py check automatic deallocation of
ALLOCATABLE INTENT(OUT) dummies on entry and copy-back of their final state,
including early RETURN, reallocation, scalar/function and character cases.
INTENT(INOUT) allocations are retained.
Optional allocatable outputs retain PRESENT even when initially unallocated;
omitted arguments remain absent.

literal_only_print.f90 and test_literal_only_print.py check literal formatted
PRINT without an item list: both quote styles, escaped quotes, nested repeats,
spacing, blank records, colon/data-descriptor termination, conditional PRINT,
and an explicit diagnostic for unsupported itemless formats.

forall_semantics.f90 and test_forall_semantics.py check statement-wise
simultaneous FORALL assignments, overlapping RHS values and LHS selectors,
array sections, multiple indices, frozen masks, index scope, descending/empty
ranges, and the distinction from sequential DO loops. Nested FORALL/WHERE
bodies and pointer assignments are diagnosed rather than lowered incorrectly.

where_semantics.f90 and test_where_semantics.py check named/nested WHERE,
ELSEWHERE and ELSE WHERE spellings, branch-name validation, frozen logical
array masks, scalar logical assignments, and masked ELSEWHERE evaluated after
preceding assignments without reselecting previously matched elements.

associate_components.f90 and test_associate_components.py check write-through
aliases to numeric component arrays, strided sections and scalar elements,
matrix sections, declared component bounds, integer conversion, expression
snapshots, enclosing-scope selector evaluation and nested/shadowed bindings.

character_lengths.f90 and test_character_lengths.py check equivalent legacy
CHARACTER*n / CHARACTER*(expr) and modern CHARACTER(LEN=expr) declarations:
initialization, padding/truncation, arrays, nested constant expressions, and
assumed-length dummy arguments.

optional_allocatable.f90 and test_optional_allocatable.py check PRESENT
independently of ALLOCATED for scalars and arrays, all intents and no INTENT,
functions, component actuals and type-bound calls. They also check allocation
changes and forwarding omitted/unallocated actuals to optional allocatables.

module_procedure_names.f90 and test_module_procedure_names.py check same-source
module procedure collisions, implicit/explicit results, module-local calls,
ONLY and renamed USE association, re-exports, private helpers, lexical shadowing,
generic and type-bound calls, scalar copyback, and ambiguity diagnostics.
Separate-file imports of qualified procedures are explicitly diagnosed.

allocatable_bounds.f90 and test_allocatable_bounds.py check allocation bounds
through allocatable dummies, indexing/sections, vector/matrix and dynamic-DIM
inquiries, reallocation/copyback, MOVE_ALLOC, SOURCE/MOLD, empty dimensions,
and ordinary assumed-shape rebasing. Runtime metadata uses weak references,
so discarded allocations do not retain stale bounds or array storage. Saved
allocatables start unallocated and retain their bounds across saved-value copies.

generic_real_kinds.f90 and test_generic_kinds.py check kind-aware named generic
dispatch: default/D-exponent/suffixed literals, declared scalars and arrays,
sections, arithmetic, known function results, keyword argument reordering,
integer/real/complex kinds, rank distinctions and empty arrays. Unmatched and
unknown numeric kinds are diagnosed rather than silently guessed.

kind_inquiries.f90 and test_kind_inquiries.py check KIND for declared numeric,
logical and character types, named kinds, literals, arrays/sections/components,
arithmetic, MATMUL/DOT_PRODUCT, conversions, and known function results.
Inquiries do not evaluate unallocated arrays or side-effecting arguments;
unknown expression kinds are diagnosed and user entities named KIND remain
ordinary procedures/arrays. Kind metadata does not emulate kind-specific
numeric storage or precision.

double_types.f90 and test_double_types.py check DOUBLE PRECISION and
DOUBLE COMPLEX declarations, attributes, arrays, parameters, components,
dummy arguments, typed function headers and KIND inquiries.
