# Four-protocol fused update main experiment

The main comparison uses 70 synthetic permutations, five in each of fourteen
size/family cells, and six fixed Drosophila chromosome-arm gene orders.
Synthetic main cases are disjoint from the pilot. The real cases are the same
six fixed inputs used in the pilot. Each input is processed by four adjacent
GPU runs in seed-42 shuffled method order. Each run performs one warm-up and
three timed calls. The comparison holds the binary, grid size, block width
(128 threads), full summary maintenance, and scalar reduction of local
virtual candidates fixed for each input.

The protocols are conditional CUDA Graph, four-barrier replicated-choice
cooperative, three-barrier fused with full writes, and three-barrier fused
with changed-interval writes. Both fused modes apply the same reversal
and derive the next summaries from the immutable old permutation. Changed
intervals restrict writes to the union of the previous and current reversal.
The [correctness proof](../../docs/PARALLEL_CORRECTNESS_THEOREM.md#8-fused-reversal-and-summary-production)
covers the fused phase and the destination-buffer invariant.

All 1,216 calls passed independent replay and matched their
archived trace hashes. Recorded cooperative grid barriers were 4R+2 and 3R+2,
respectively. The runner reused the two validated pilot binaries and completed
in 5.42 minutes including replay and logging. Both
fused modes add one (n+2)-entry integer buffer. See
[provenance](provenance.json) for binary hashes and the GPU.

## Timing and figure

End-to-end time includes per-call allocations, transfers, sorting, retrieval,
cleanup and fresh Graph setup/upload/teardown. It excludes context startup,
file I/O and independent replay. The reported ratio divides the first method's
time by the second method's time. Each synthetic cell is the median of five
paired ratios computed after taking the three timed repetitions' median for
each input and method. Descriptive 95% percentile intervals use 10,000
paired-input bootstrap draws with seed 42. The intervals are unadjusted and
the synthetic cells contain five independent inputs each. Real results are
reported case by case.

| Pairwise comparison | Synthetic medians, range | Cells above parity | Intervals wholly above parity | Real cases, range |
| --- | ---: | ---: | ---: | ---: |
| Graph / four barriers | 1.333–1.560 | 14/14 | 14/14 | 1.372–1.417 |
| Graph / full copy | 1.415–1.771 | 14/14 | 14/14 | 1.189–1.547 |
| Graph / changed intervals | 1.431–1.805 | 14/14 | 14/14 | 1.413–1.541 |
| Four barriers / full copy | 1.065–1.175 | 14/14 | 14/14 | 0.865–1.106 |
| Four barriers / changed intervals | 1.065–1.219 | 14/14 | 14/14 | 1.005–1.109 |
| Full copy / changed intervals | 0.974–1.038 | 11/14 | 4/14 | 0.959–1.189 |

| n | Family | Graph / four barriers | Graph / full copy | Graph / changed intervals | Four barriers / changed intervals |
| ---: | --- | ---: | ---: | ---: | ---: |
| 2,048 | uniform | 1.415 | 1.629 | 1.617 | 1.139 |
| 2,048 | semi | 1.420 | 1.561 | 1.566 | 1.087 |
| 4,096 | uniform | 1.421 | 1.632 | 1.646 | 1.159 |
| 4,096 | semi | 1.394 | 1.486 | 1.510 | 1.083 |
| 8,192 | uniform | 1.444 | 1.667 | 1.669 | 1.154 |
| 8,192 | semi | 1.416 | 1.527 | 1.526 | 1.084 |
| 16,384 | uniform | 1.511 | 1.748 | 1.752 | 1.159 |
| 16,384 | semi | 1.442 | 1.566 | 1.576 | 1.091 |
| 32,768 | uniform | 1.539 | 1.771 | 1.778 | 1.155 |
| 32,768 | semi | 1.449 | 1.558 | 1.562 | 1.075 |
| 65,536 | uniform | 1.560 | 1.762 | 1.805 | 1.157 |
| 65,536 | semi | 1.460 | 1.541 | 1.549 | 1.068 |
| 131,072 | uniform | 1.432 | 1.684 | 1.747 | 1.219 |
| 131,072 | semi | 1.333 | 1.415 | 1.431 | 1.065 |

| Real input | Markers | Graph (ms) | Four barriers (ms) | Full copy (ms) | Changed intervals (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| real-v1-dmel-dsim-2R | 2,565 | 0.4400 | 0.3202 | 0.3700 | 0.3113 |
| real-v1-dmel-dsim-3L | 2,505 | 0.4348 | 0.3069 | 0.2928 | 0.3054 |
| real-v1-dmel-dsim-3R | 3,109 | 1.1297 | 0.8048 | 0.7303 | 0.7330 |
| real-v1-dmel-dyak-3L | 2,415 | 0.9152 | 0.6461 | 0.5960 | 0.6161 |
| real-v1-dmel-dyak-3R | 3,060 | 0.9505 | 0.6926 | 0.6262 | 0.6244 |
| real-v1-dmel-dyak-X | 1,890 | 0.6806 | 0.4933 | 0.4689 | 0.4696 |

## Interpretation

The changed-interval variant gives shorter point estimates than the
four-barrier reference in 14 of 14 synthetic cells. The descriptive
interval lies entirely above parity in 14 cells. The changed-interval
variant is faster than full copy on 49 of 70 synthetic inputs and
2 of six real inputs. The two fused variants share the same number
of barriers and the tested full summary scan. Relative to full copy, the
changed-interval variant reduces logical permutation store counts by
51.1%–97.7% including initialization. These counts follow
from the certified traces. Timing effects also include interval tests,
access patterns and memory hierarchy effects.

The changed-interval schedule is the primary manuscript variant. Full copy
is the matched control for its write strategy. For n=131,072 uniform inputs,
representative medians were 2.212 s for Graph, 1.544 s for four barriers,
1.314 s for full copy and 1.266 s for changed intervals. The paired speedup
of changed intervals over Graph declines from 1.805 at 65,536 to 1.747 at
131,072 for uniform inputs. For semi-random inputs it declines from 1.549
to 1.431 over those sizes.

The variant with three barriers combines update and summary production.
Its matched benefit measures that whole change. Variations across n are
also variations across the shared launch rule's grid size. The results
cover one GPU and the selected synthetic and biological inputs.

[Paired statistics](paired-cells.csv) ·
[Input medians and method order](pairs.csv) · [Verified measurements](measurements.jsonl)

The measurement records include trace hashes. See the
[artifact guide](../../ARTIFACT.md) for trace replay and figure reproduction.
