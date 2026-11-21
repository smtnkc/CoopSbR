# Fixed CUDA Graph comparison subset

Twenty saved synthetic main inputs: n=65536 and 131072, uniform and semi-random
k=64, first five saved main inputs in each cell. Eight synthetic pilot inputs:
the two separately saved pilot files in each corresponding cell. All six fixed
real chromosome-arm inputs are retained for feasibility and main evaluation.
No data are generated, concatenated, padded or chosen by observed speedup.

Seed-42 scheduling reuses these exact bytes across both versions. Both versions
use full updates, local virtual candidate evaluation and scalar reduction.
They differ in cooperative versus conditional WHILE Graph coordination only.
Graph setup/upload/instantiation and teardown occur afresh in every sorting
call and are included in end-to-end time, with their own reported metrics.

One warm-up and three main measurements yield 208 sorting calls; pilots use
one warm-up and two measurements (84 calls including all fixed real cases).
The real corpus is fixed; repeated timings are not additional biological inputs.
