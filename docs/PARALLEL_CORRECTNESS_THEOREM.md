# Decision-boundary equivalence of GPU reversal sorting

Reviewed source revision: `ce5bad68e0d32fca806ce39c156720311a2d6889`.
This is a mathematical argument checked against the implementation, not a
proof-assistant certificate or a claim of a new approximation factor.

The [policy proof](APPROXIMATION_PROOF.md), Sections 1-5, establishes the
sequential policy's termination and approximation guarantee. The theorem here
establishes preservation of that policy by the parallel execution design. The
statement is independent of measured speedups and applies to both full and
incremental summary maintenance.

## 1. Model and notation

Let P=(0,p_1,...,p_n,n+1), where p_1,...,p_n is a permutation of 1,...,n,
and let rho=[l,r], 1<=l<r<=n, reverse the indicated internal positions.
Write P rho for the resulting permutation. Sentinels never move. Define

\[
 B_P(i)=\begin{cases}1,&i>0\text{ and }|P_{i-1}-P_i|\ne1,\\0,&\text{otherwise},\end{cases}
\]

and, for 1<=i<=n,

\[
 d_P(i)=\mathbf 1\{P_{i-1}=P_i+1\ \lor\ P_{i+1}=P_i-1
       \ \lor\ (B_P(i)=1\land B_P(i+1)=1)\}.
\]

Set d_P(0)=d_P(n+1)=0. This is exactly decreasing-strip membership,
including interior singleton strips. Let D(P)=sum_i d_P(i) and
b(P)=sum_i B_P(i). D(P) counts elements, not strips.

Partition positions 0,...,n+1 into disjoint fixed chunks J_0,...,J_{q-1}.
The implementation uses consecutive chunks of C=256 positions, with a possibly
short last chunk. For a position set J, let S(P,J) contain:

- the minimum and maximum labels P_i for which i is in J and d_P(i)=1;
- sum_{i in J} d_P(i) and sum_{i in J} B_P(i);
- the two smallest indices i in J with B_P(i)=1.

Use +infinity and 0 for empty minimum/maximum and +infinity for missing
breakpoint indices, as in `Summary`. The inverse array is pos[P_i]=i.
Let A be precisely `extreme-strip-v1` in [POLICY.md](POLICY.md), including its
singleton convention, fixed endpoint formulas and minimum-candidate predicate.
Let P^t and T^t be A's permutation and reversal prefix after t reversals.

## 2. Execution assumptions and boundary invariant

The implementation-level theorem uses these explicit assumptions:

**A1 — Input and storage.** The input is a valid distinct-label permutation.
Buffers do not alias improperly and have sufficient capacity. Index arithmetic,
counts, signed candidate deltas and their intermediate reductions are
representable in their implementation types. In particular, the trace has at
least b(P^0) slots; the current n+1 slots suffice because b(P^0)<=n+1.

**A2 — Execution.** CUDA operations succeed and scheduled finite work makes
progress. No external operation mutates solver buffers while sorting. The
supported block sizes are 32, 64, 128 or 256, all threads required by a collective
participate, and shared reduction storage is synchronized before reuse.
Cooperative execution uses a supported cooperative launch and a grid admitted by
the actual kernel's residency bound. This is not a liveness guarantee under
hardware failure, cancellation or an unsupported launch.

**A3 — Phase protocol.** The implementation assigns each chunk and each swap
pair once, has one writer for the shared reversal choice and trace append,
and publishes producer writes before dependent reads. Cooperative execution uses
the grid barriers listed below; Graph execution uses ordinary full kernel
completion dependencies and its conditional-loop semantics. These are concrete
ordering obligations, not an assumption that the sorting result is correct.

Define boundary E_t immediately before preparation of decision t, after all
updates for the previous reversal have completed (or after initialization for
t=0). Its invariant I_t is:

1. The device permutation equals P^t, including the two fixed sentinels.
2. pos[P^t_i]=i for every position i.
3. Every stored chunk equals S(P^t,J_c).
4. The trace count is t and its prefix equals T^t, with external zero-based
   inclusive endpoints corresponding to internal [l,r] by [l-1,r-1].
5. The writes establishing these facts are visible to every phase that consumes
   them, and no earlier update remains in progress.

The cached root summary, candidate, partials and chosen interval need not be
current at E_t: preparation/evaluation refresh them before their next use.
Likewise I_t is not asserted in the middle of a swap or immediately after a
trace append. The append records a pending step that becomes completed at E_{t+1}.
This distinction avoids claiming continuous consistency during parallel updates.

## 3. Supporting lemmas

**Lemma 1 (exact summaries).** For disjoint position sets J and K, combining
S(P,J) and S(P,K) yields S(P,J union K), independently of reduction-tree order.

*Proof.* Counts add and extrema take min/max. The two smallest breakpoint
indices in the union must occur among the two smallest from each input set;
`combine` retains exactly those two. Each position is included once, so no
finite breakpoint index is duplicated. The empty summary is an identity.
Consequently repeated combination yields the summary of the union under any
parenthesization, including noncontiguous thread-local partitions. Integer
arithmetic under A1 makes this equality exact. QED.

**Lemma 2 (exact virtual candidate count).** For rho=[l,r], let W be the union
of all complete chunks intersecting [l-1,r+1]. Then

\[
 D(P\rho)=D(P)+\sum_{i\in W}\bigl(d_{P\rho}(i)-d_P(i)\bigr).
\]

*Proof.* Reversal changes P only inside [l,r]. Membership d_P(i) reads only
positions i-1,i,i+1; hence it is unchanged outside [l-1,r+1]. W contains that
entire affected set, and extra positions in its chunk fringes contribute zero
net change. The stored old decreasing counts sum to sum_{i in W}d_P(i), and
`viewed` reads P rho exactly without changing P. Thus subtracting the old chunk
counts and adding virtual counts gives the displayed identity. Scanning the
whole permutation or materializing P rho gives the same count. Summary-field
and scalar reductions both add the same signed deltas; a negative partial must
be retained. Empty block assignments contribute zero. QED.

**Lemma 3 (exact state repair).** Applying the disjoint reversal swaps, updating
the positions of moved labels, and rebuilding all chunks intersecting
[l-1,r+1] restores the permutation, inverse-array and chunk invariants for P rho.

*Proof.* Swap k exchanges positions l+k and r-k, for
0<=k<floor((r-l+1)/2). Distinct k values touch disjoint positions and, because
labels are distinct, disjoint inverse-array entries. Each pair updates both
moved labels' inverse positions. An odd middle position is unchanged, as are
all other labels, so their old inverse entries remain valid. Sentinels lie
outside the reversal.

A leaf's membership can change only in [l-1,r+1]. Its breakpoint indicator
reads P_{i-1},P_i and can change only in [l,r+1]. Its extrema contribution reads
membership and its current label, which also cannot change outside the expanded
interval. Therefore every leaf outside the rebuilt chunks stays valid.
Recomputed chunks are exact by Lemma 1; retained chunks are unchanged. Full
rebuilding is the special case that recomputes all chunks. QED.

**Lemma 4 (ordered phases realize one policy step).** If I_t holds and P^t is
not identity, preparation, candidate evaluation, choice, reversal and summary
repair produce I_{t+1} and append A's next reversal.

*Proof.* Lemma 1 makes the prepared root equal to S(P^t,{0,...,n+1}). If
D(P^t)=0, preparation selects the interval between the first two breakpoints,
as A does; no candidate partial is read. Otherwise exact extrema and inverse
positions give A's minimum witness. Lemma 2 makes `count>0` exactly A's
existence predicate for a decreasing element after that virtual reversal.
Thus choice selects the same minimum or maximum witness as A.

One thread appends that interval once. Its publication precedes all swap reads;
all swaps complete before repair reads the new permutation. Lemma 3 restores
the arrays and summaries, and repair is published before the next preparation.
The trace prefix now corresponds to the completed reversal. These facts give
every component of I_{t+1}. QED.

## 4. Main theorem: decision-boundary equivalence

**Theorem 1.** Under A1-A3, starting from the same valid input as A, each current
GPU backend (cooperative, conditional WHILE Graph, or ordered separate launches)
with either full or incremental summary maintenance produces exactly A's
reversal sequence and final permutation. This holds with local virtual, full
virtual or materialized candidate evaluation and either summary-field or scalar
candidate reduction. At every reached decision boundary E_t, I_t holds.
If A terminates after R reversals, the GPU backend completes exactly those R
reversals and reports successful termination at the same identity permutation.

*Proof.* Initialization copies P^0, writes the inverse position of each distinct
label once, and constructs exact initial chunks. The trace count starts at zero.
After publication, I_0 holds. In the cooperative kernel, initial chunk building
reads only the unchanged permutation: it does not read inverse entries or the
new State, so it may overlap position/State initialization before the first
grid barrier without violating this base case.

Assume I_t. Exact preparation detects completion if and only if b(P^t)=0,
which, with fixed sentinels, is equivalent to identity. In an error-free run
this stops without an extra append or reversal. Otherwise Lemma 4 gives the
same next reversal as A and establishes I_{t+1}. Mathematical induction proves
equality of every completed state and prefix. A2-A3 ensure that each finite
phase completes, so the induction also reaches the sequential terminal state;
this is not merely equivalence conditional on eventual GPU completion. QED.

**Corollary 1 (termination and inherited approximation guarantee).** For the
policy A established in Sections 1-5 of [APPROXIMATION_PROOF.md](APPROXIMATION_PROOF.md),
Theorem 1 implies a valid sorting trace with

\[
 R_{\mathrm{GPU}}=R_A\le b(P^0)\le 2\,\operatorname{OPT}(P^0).
\]

The factor two follows from that policy argument and the breakpoint lower
bound, not from CUDA scheduling. Identity inputs execute no reversal.

**Corollary 2 (configuration-independent trace).** Any two supported
configurations covered by Theorem 1 produce identical endpoints in the same
order for the same input. Different reduction trees, valid grid sizes and
update modes may change execution time, but cannot change the trace under the
stated assumptions.

## 5. How the code discharges the phase obligations

| Phase | Relevant code | Ownership and publication obligation |
| --- | --- | --- |
| Initialize | `positions`, initial `chunks_update` | Unique inverse writes and chunk owners; initial publication before preparation. |
| Prepare | `prepare`, `minimum_reversal` | Block 0 computes the exact root; its thread 0 publishes termination, candidate or strip choice. |
| Optional copy | `materialize`, `viewed` | Unique temporary-array writes, followed by publication before evaluation. |
| Evaluate | `evaluate`, `block_reduce`, `scalar_block_sum` | Each selected chunk contributes once; every block writes its current partial, including zero for an empty assignment. |
| Choose and append | `choose`, `maximum_reversal` | Only block 0/thread 0 reads the partials and appends; the chosen interval is published before swaps. |
| Reverse | `reverse_values` | Disjoint swaps and inverse writes; all swaps complete before summaries read the new state. |
| Repair | `chunks_update` | One owner per rebuilt chunk, with block-wide reduction; publication before the next preparation. |

In cooperative execution, all threads encounter the same grid barriers after
initialization, preparation, evaluation, choice, reversal and repair. There is
an additional grid barrier after materialization when that mode needs a
candidate. Published shared flags make these branch choices uniform across the
grid. The current protocol has five grid barriers per successful reversal
(preparation, evaluation, choice, reversal, repair), plus the initial and final
preparation barriers; materialization adds one for each evaluated candidate.
Within a chunk loop, all threads in a block take the same chunk assignments and
participate in the block reductions. Scalar warp reductions do not themselves
publish shared/global memory; the surrounding block/grid synchronization does.

In the Graph, initialization -> initial summaries -> prepare -> WHILE orders
the first decision. Each body orders optional materialization -> evaluate ->
choose -> reverse -> repair -> prepare with full kernel dependencies.
`graph_prepare_kernel` launches one block; its thread 0 sets the continuation
handle after completing preparation. The handle is nonzero exactly when the
state is neither done nor in error. The next body can run only after the previous
body completes, so it consumes that prepared state. Identity skips the body.
Ordered separate launches satisfy the same obligations through stream order
and the status copy preceding the next host-controlled iteration.

Termination with an error flag, capacity failure, CUDA failure or external
cancellation is not a successful sorting result and is outside the theorem's
completion conclusion. In a run satisfying A1-A3 and the proven policy,
invalid-reversal/capacity/debug-progress failures cannot occur: valid choices
follow from the policy proof, state checks follow from I_t, and R<=b(P^0)
ensures sufficient trace capacity.

## 6. Scope of the proof

Reviewed source files (SHA-256 at the revision above):

- [`src/gpu.cu`](../src/gpu.cu): `26ca6d7ad94b20e65c25b9e90081b973bf5f94c3ed5f0d34f1c0685ba294c5b7`
- [`include/coopsbr/policy.hpp`](../include/coopsbr/policy.hpp): `63ad30dfba2753f7b9146982b7e09ab4d1d98ed778dea12cd24d7a221b79992f`
- [`src/sequential.cpp`](../src/sequential.cpp): `a71138a4db57459c3dc574e3e2f24c582ee3c4b4d66d65935875345a6f260d73`

Existing exact small-input and GPU-equivalence tests support this review, but
they are finite regression evidence, not the proof of the universal statement.
The theorem does not establish speedup, a minimal barrier count, formal
verification of the CUDA compiler/runtime, or originality relative to prior
parallel algorithms. A change to phase order, ownership, summary semantics or
representation must discharge the affected obligations again.

The CUDA ordering premises rely on NVIDIA's documented semantics:
[Cooperative Groups and grid synchronization](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html#grid-synchronization),
[group synchronization](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html#sync),
[Graph dependencies](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html#graph-structure),
and [conditional Graph nodes](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html#conditional-graph-nodes).


## 7. Extension to replicated reversal choice

The backend introduced in source revision fd80707 preserves the theorem with
four grid barriers per successful reversal under local or full virtual
evaluation. The original cooperative backend uses five. Initialization and
terminal preparation add two barriers in both. Materialized evaluation adds
one barrier per candidate it materializes.

**Proposition.** Under A1-A3, the replicated-choice phase produces the same
reversal as the original single-writer choice and preserves the
decision-boundary invariant. The grid barrier between choosing and reversing
can be omitted in this phase protocol.

*Proof.* Preparation computes the minimum and maximum witness endpoints from
the same exact root summary and inverse array. It publishes both witnesses
before evaluation. On the strip path, preparation publishes the strip interval
instead. Evaluation completes and publishes every block partial before any
block selects or applies the reversal. The witness endpoints, candidate
partials and root decreasing count stay fixed while reversal workers run.

On the candidate path each block reduces the same signed partials and adds the
same old count, so Lemma 2 gives an identical count in every block. The block
publishes its count to its own threads with block synchronization. The fixed
predicate selects the same interval in every block. On the strip path every
thread uses the already published interval directly. Validation depends on the
same interval, common local iteration number and, in debug mode, a full virtual
count computed during preparation. All blocks therefore take the same success
or failure branch.

Each worker uses its local interval and the disjoint swaps of Lemma 3. It reads
neither the changing inverse array to choose an interval nor the interval saved
by the trace writer on the candidate path. The unique trace writer records the
interval once and publishes it for summary repair along with the completed
swaps at the post-reversal barrier. On the strip path it leaves the published
interval alone. Repair and its publication establish the next decision
boundary as before. Thus the same induction and corollaries apply. QED.

For B blocks, replicating the reduction of B partials uses O(B^2) aggregate
partial reads instead of O(B). The reads are distributed across block threads.
The reduced barrier count is a structural result. Its timing effect depends on
this extra work and is evaluated with the same input, block count, candidate
evaluation, and update mode in the benchmark.


## 8. Fused reversal and summary production

The pilot source revision dcdc2fd adds two cooperative modes with an
additional permutation buffer. Both use the replicated choice from Section 7.
For local or full virtual candidate evaluation, a successful run with R
reversals executes 3R+2 grid barriers. The per-reversal barriers follow
preparation, evaluation, and fused update. Materialized candidate evaluation
adds a barrier for each materialized candidate.

**Proposition.** Under A1-A3 and with two distinct permutation buffers, the
fused update preserves I_t and the identical trace guarantee in Theorem 1.
In the changed-interval mode, the destination can retain all entries outside
the union of the preceding and current reversal intervals.

*Proof.* At boundary E_t the source is P^t. Section 7 gives the same chosen
interval to all blocks. While the fused phase runs, the source is immutable.
Let v(i) map i to l+r-i inside the chosen inclusive interval [l,r] and to i
outside it. The next permutation is Q_i=P^t_{v(i)}. Each position has one
thread responsible for its destination entry. Each changed inverse entry
pos[Q_i] is written by its position owner. The distinct-label input makes
those writes disjoint. Labels outside [l,r] keep their prior positions.

A leaf summary for Q depends only on Q_i and its adjacent values. Each of
these reads is evaluated as P^t_{v(j)} in the source. The fused phase thus
computes exactly the same summary as scanning the completed Q, independently
of when other threads write the destination. By Lemmas 1 and 3, full rebuild
and the existing incremental rebuild both give exact chunk summaries.

The full-copy mode writes every Q_i. For the changed-interval mode both
buffers start with P^0, so only the current reversal needs an entry update on
the first step. At later steps, the destination held P^{t-1} and the source
holds P^t. Outside the preceding reversal interval they already agree. Outside
the current reversal interval Q agrees with P^t. Consequently the destination
already equals Q outside their union. Each position in the union is assigned
once, including positions in the overlap. The destination now holds Q and the
source still holds P^t.

The fused phase's grid barrier publishes the completed destination, inverse
positions, chunk summaries and trace. Each thread then swaps its local source
and destination pointers. Every thread uses the same parity, so no shared
pointer publication is necessary. At the next decision boundary the source,
inverse array and summaries satisfy I_{t+1}. The inactive buffer contains the
previous permutation, establishing the extra premise for the next fused step.
Induction gives the same trace, termination and approximation guarantee. QED.

The changed-interval implementation reduces permutation writes. With full
summary maintenance it still visits every position to rebuild the summaries.
Its write count is (n+2) for initialization plus the sum of the sizes of the
two-interval unions. The count is a logical store count, with measured
execution time reported separately.
