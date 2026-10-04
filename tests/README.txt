Fortran-to-Python execution tests
================================

Run from the repository root:

    python -m pip install numpy scipy pytest
    pytest -q -rx

Requirements: Python, NumPy, pytest, and gfortran on PATH. Execution tests
skip explicitly if gfortran or NumPy is missing; they do not pretend to pass.
SciPy is optional for the translator/runtime and ordinary translated programs;
special-function programs require it. The math_intrinsics and
modern_math_intrinsics execution comparisons
and SciPy-specific unit test skip explicitly when SciPy is unavailable.
Each subprocess has a 90-second timeout. Compiler commands use argument lists,
so Windows paths with spaces work without shell quoting.

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
Integer tokens are compared exactly; real tokens use relative tolerance
1e-9 and absolute tolerance 1e-11, accepting Fortran D exponents.
This is numerical-output validation, not byte-for-byte formatting validation.
Original Fortran and translated Python run in separate directories, so file
I/O cannot accidentally reuse files produced by the reference execution.

Known failures (2026-10-04)
--------------------------
formatted_file_io: numeric file units produce invalid Python 20.close().
execute_command_line: missing EXECUTE_COMMAND_LINE helper.
selected_integer_kind, selected_logical_kind, selected_real_kind: missing
kind-selection intrinsic helpers.
type_extension: missing parent component of an extended type.

These cases are strict expected failures, not skipped. Their Fortran
references must still compile and execute successfully. Unexpected success
fails the suite so that obsolete expectations are removed after a fix.
Other assertion failures inside a known-failing translation may also count
as expected failures; inspect their tracebacks when changing the translator.

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
are not yet supported by this implementation; type extension remains failing.

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
