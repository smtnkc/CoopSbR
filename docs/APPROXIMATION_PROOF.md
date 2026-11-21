# Approximation guarantee of the implemented policy

Review date: 16 November 2026. Applies to `extreme-strip-v1` in
`include/coopsbr/policy.hpp`, `src/sequential.cpp`, and `src/gpu.cu`.

**Conclusion.** For a permutation of the distinct labels 1 through n with fixed
sentinels 0 and n+1, the implemented policy terminates, returns a valid sorting
trace, and uses R <= b(initial) <= 2 OPT reversals. Both GPU update choices and
both coordination choices produce the same trace as SEQ. The previously stated
claim that the two extreme witnesses must coincide is unnecessary and false.
No reversal-selection code change is needed for the corrected argument below.

This is a mathematical derivation and code-level invariant review, not a
machine-checked proof. Exhaustive tests are supporting checks, not its basis.
The factor two is established literature, not a new approximation ratio.

## 1. Model and definitions

Write the augmented permutation as p[0],...,p[n+1], with p[0]=0 and
p[n+1]=n+1. A breakpoint is an edge whose absolute value difference is not one.
A strip is a maximal interval without breakpoints. A nontrivial strip is either
strictly increasing or strictly decreasing: a change of direction along
unit-difference edges would repeat a label. Interior singleton strips are
classified as decreasing; singleton sentinel strips are increasing. All elements
of a strip have its classification. Reversals have inclusive internal endpoints
1 <= l < r <= n. External trace endpoints are l-1,r-1.

Let b(p) be the breakpoint count, D(p) the set of labels in decreasing strips,
and OPT(p) the minimum number of allowed reversals to identity. An interior
element is decreasing exactly when its left neighbor is one greater, its right
neighbor is one smaller, or both incident edges are breakpoints. Consequently
its classification depends only on those two neighbors.

**Basic facts.** A reversal preserves the number of internal breakpoint edges;
only its two external edges can change. Thus it removes at most two breakpoints,
and OPT(p) >= ceil(b(p)/2). The strips touching either sentinel are increasing.
With zero breakpoints, the strip starting at 0 must be 0,1,...,n+1. There cannot
be exactly one breakpoint: the increasing prefix from 0 and increasing suffix
ending at n+1 would partition the label range into two consecutive ranges, whose
joining edge is also an adjacency. Consequently every nonidentity state has at
least two breakpoints.

## 2. Extreme witnesses are valid and remove a breakpoint

Suppose D(p) is nonempty. Define m=min D(p), M=max D(p), and positions

- a=pos(m-1), b=pos(m),
- d=pos(M), c=pos(M+1).

Here b is a position, distinct from the notation b(p).

The element m ends its decreasing strip: extending the strip rightward would
include m-1, contradicting minimality. The element m-1 is in an increasing strip
and ends it: an increasing successor would be m, placing m in that increasing
strip. Similarly M starts its decreasing strip and M+1 starts an increasing
strip. These statements include the possible singleton sentinels.

Therefore the edges cut after positions a and b, and before positions d and c,
are breakpoints. The corresponding endpoints cannot be adjacent; otherwise m
and m-1, or M and M+1, would belong to one strip with contradictory
classifications. Both reversals are nontrivial, avoid the sentinels, and reverse
unions of whole strips:

- rho-min = [min(a,b)+1, max(a,b)],
- rho-max = [min(d,c), max(d,c)-1].

rho-min joins m-1 with m. rho-max joins M with M+1. Each repairs one of two
previously broken boundary edges, and the other boundary edge cannot become
worse than a breakpoint. Each therefore decreases b(p) by one or two.

## 3. The required two-witness lemma

**Lemma.** If neither p after rho-min nor p after rho-max contains a decreasing
strip, rho-max removes two breakpoints.

**Proof.** If b<a, rho-min creates the decreasing adjacency (m,m-1), contradicting
the premise. If c<d, rho-max creates (M+1,M), also a contradiction. Thus a<b and
d<c. Let I=[a+1,b] and J=[d,c-1] be the reversal intervals.

Because each interval reverses whole strips, it cannot contain an increasing
strip of length at least two: reversal would leave a descending unit adjacency
inside that strip. Sentinel singletons are outside these legal intervals.
All positions in I and in J must therefore belong to decreasing strips of the
original permutation, including its interior singletons.

Outside a reversed interval, an element's strip classification can change only
at the immediately adjacent position, since it depends on its two neighbors.
The original label M at d is decreasing. For rho-min to remove its decreasing
classification, d must lie inside I or at one of its neighboring positions a,
b+1. It is not a, which contains m-1. Hence a<d<=b+1. Applying the same argument
to m at b and rho-max, b is inside J or at d-1,c; it is not c, which contains
M+1. Hence d-1<=b<c.

The left fringe I outside J has positions a+1,...,d-1. If it contained a position
at most d-2, that position would be originally decreasing, outside J and not
adjacent to J, and would stay decreasing after rho-max. Thus d<=a+2. Symmetrically
the right fringe J outside I, at b+1,...,c-1, cannot contain a position at least
b+2; thus c<=b+2. In combination,

    d is a+1 or a+2, and c is b+1 or b+2.

Consider the two possible left fringes:

1. **One-position left fringe, d=a+2.** Let x=p[d-1]=p[a+1]. It is originally
   decreasing, whereas its left neighbor p[a]=m-1 is increasing. Their edge is
   a breakpoint. rho-max does not change that edge. After rho-max there are no
   decreasing strips, so the interior element x must have an increasing
   adjacency to its new right neighbor; otherwise it would be a decreasing
   singleton or in a decreasing strip. That neighbor is p[c-1]. Therefore
   p[c-1]=x+1. rho-max repairs its left boundary as well as its guaranteed right
   boundary (M,M+1): two breakpoints are removed.
2. **Empty left fringe, d=a+1.** If c=b+1 also, I=J and rho-max repairs both
   (m-1,m) and (M,M+1). The only alternative is c=b+2. Let y=p[b+1]=p[c-1]. It
   is originally decreasing (inside J); its right neighbor p[c]=M+1 is
   increasing, so that edge is a breakpoint and remains unchanged by rho-min.
   In the rho-min result, y must instead have an increasing adjacency on its
   left. Its new left neighbor is p[a+1]=p[d]=M. This requires y=M+1, repeating
   the label at c. That alternative is impossible.

All possible cases give a decrease of two for rho-max. QED.

**Why witness equality was wrong.** For augmented [0,3,6,5,2,1,4,7], m=1 and
M=6 give a=0,b=5,d=2,c=7. The one-position left and right fringes contain 3 and
4. I=[1,5] and J=[2,6] differ, but both repair two breakpoints (5 to 3). The
proof above explicitly permits this case.

## 4. The no-decreasing-strip step

If p is unsorted and has no decreasing strip, it has at least two breakpoints.
The interval between the first two is an interior increasing strip [x,...,y]
with length at least two: an interior singleton would be decreasing. It contains
neither sentinel, so the implemented reversal is legal and creates a decreasing
strip.

Its boundaries remain breakpoints. At the left, a new neighbor of y cannot be
y-1 (already inside the reversed strip). If it were y+1, the preceding increasing
strip would also contain y, unless it were a singleton; interior singleton strips
are excluded, and the sentinel 0 cannot equal y+1. At the right, a new neighbor
of x cannot be x+1 (already inside the strip). If it were x-1, the following
increasing strip would also contain x; the singleton sentinel n+1 cannot equal
x-1. Both joins therefore remain broken. This step decreases the number of
breakpoints by exactly zero and creates decreasing membership.

## 5. Termination and factor two

Define the integer potential

    Phi(p) = b(p) + 1 if p is unsorted and D(p) is empty,
             b(p)     otherwise.

For the strip-flip step, b stays fixed and the extra indicator disappears;
Phi decreases by one. A positive step retaining a decreasing strip removes at
least one breakpoint and decreases Phi by at least one. If a positive step
leaves an unsorted state without decreasing strips, rho-min was rejected and
rho-max also leaves none. Section 3 then gives a breakpoint decrease of two;
the new indicator costs one, so Phi still decreases by one.

The potential is nonnegative and each step reduces it, so the process terminates.
The only terminal state is identity. Its final reversal removes at least two
breakpoints (a nonidentity state cannot have just one), hence exactly two. The
pre-final state has decreasing membership, because a strip flip cannot sort.
The final potential decrease is therefore two. For any initially unsorted p,

    R <= Phi(p)-1 <= b(p) <= 2 OPT(p).

More precisely R <= b(p)-1 when the initial state already has a decreasing strip;
otherwise R <= b(p). Identity uses R=OPT=0 and needs no ratio division.

## 6. The parallel implementations preserve the policy

The complete decision-boundary invariant, supporting lemmas, formal theorem
and code-level phase obligations are recorded in
[PARALLEL_CORRECTNESS_THEOREM.md](PARALLEL_CORRECTNESS_THEOREM.md).
The argument below is a summary; the detailed theorem also covers the
conditional Graph backend and both candidate-reduction modes.

The following induction starts with the same input and positions on CPU/GPU.

1. **Membership.** For an interior label v at index i, it is decreasing iff its
   predecessor is v+1, its successor is v-1, or both incident edges are
   breakpoints. These are exactly nontrivial decreasing strips and isolated
   interior singletons. Sentinels are excluded. This is `decreasing_at`.
2. **Summary reduction.** Min/max labels, integer counts, and the first two
   breakpoint indices combine by associative operations on disjoint position
   sets. The root summary is exact regardless of the reduction tree.
3. **Virtual evaluation.** Reversing [l,r] can change membership only within
   [l-1,r+1]. Removing old counts of intersecting chunks and adding their virtual
   counts therefore gives exactly the full virtual count. Aligned chunk fringes
   add extra computation, not an approximation. Full and materialized modes
   evaluate the same virtual permutation.
4. **Updates.** Physical swap pairs are disjoint. Both moved positions are
   updated; the middle position, if any, is unchanged. Rebuilding all chunks
   intersecting [l-1,r+1] repairs every potentially changed position, membership,
   or breakpoint summary; all other chunk summaries remain valid.
5. **Visibility and decision.** The launch version orders dependent kernels
   and status copies in one stream. The cooperative version uses grid barriers
   before reading shared decisions or updated state, including the extra barrier
   after materialization. Its grid is bounded by actual kernel residency. Root
   decisions are made once, use integer reductions, and obey the same fixed
   branch order and endpoint formulas.

Thus each next reversal and resulting permutation are equal to SEQ. Induction
proves trace equality, termination, and the same approximation bound for the
four update/coordination combinations. This statement assumes successful CUDA
execution, a valid cooperative grid, sufficient trace capacity, and no external
mutation of solver buffers; error/timeout runs are not sorting solutions.

## 7. Relation to literature and validation

The breakpoint lower bound and the classical strip-based factor-two principle
are due to Kececioglu and Sankoff (1995),
[original paper](https://assets.uniweb.app/dist/LgmvpDDAFTVZu2u5n9Ncoo/base.pdf),
DOI [10.1007/BF01188586](https://doi.org/10.1007/BF01188586).
The paper's greedy implementation and singleton conventions should not be
silently equated with this fixed two-witness instantiation. Sections 2-5 above
supply the needed argument for the code's specific conventions.

The finite test suite checks all 46,233 permutations through n=8 against exact
BFS distances, independent replay, and the structural progress conditions.
Additional tests check the fringe cases and potential accounting. These checks
can detect implementation mistakes, while the unbounded-n guarantee follows
from the argument above. The old CPU/MPI code is referenced in
[FastSbR](https://github.com/smtnkc/FastSbR); the GPU update/coordination design,
not the approximation constant, is the research contribution.

## Optional scalar candidate reduction

The scalar reduction changes no candidate or decision predicate. If thread t
contributes delta_t, both the original Summary reduction's decreasing field and
the new integer reduction return sum_t delta_t. combine adds that field without
filtering it; signed negative deltas are retained. Complete warp participation
and block synchronization ensure the same partials reach the unchanged choose
routine. Thus all reversal endpoints, the potential argument and R <= 2 OPT
remain the same, subject to the implementation's existing index bounds. This is
an implementation-equivalence argument, not a new approximation result.

## Conditional Graph execution equivalence

Initialization and initial summaries precede prepare by graph dependencies.
Prepare supplies exactly the same candidate or strip decision and sets the
continuation handle from done/error. Each WHILE body orders evaluation, choice,
physical reversal, summary update and next prepare by full kernel dependencies.
Consequently every decision consumes the state from the immediately preceding
reversal. Identity inputs skip the body; errors clear the handle and are
reported. All policy functions, tie-breaking and index definitions are shared
with the existing backends, so deterministic trace equivalence and the same
potential-based 2-approximation argument apply. Graph scheduling itself changes
neither the choice policy nor the bound.
