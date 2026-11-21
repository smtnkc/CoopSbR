# CoopSbR: Trace-preserving GPU sorting of unsigned permutations by reversals

CoopSbR sorts one unsigned permutation by reversals on a single NVIDIA GPU.
The cooperative GPU solver produces exactly the same reversal sequence as
the deterministic C++17 reference. The primary GPU variant uses three
grid-wide barriers per reversal and limits writes to the two intervals
needed to keep its alternating permutation buffers correct.

## Build and verify

CMake 3.24 or later and a C++17 compiler are required. Python 3 is used by
the workflow tests and data tools.

```sh
cmake -S . -B build/cpu -DCOOPSBR_ENABLE_CUDA=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build/cpu --parallel
ctest --test-dir build/cpu --output-on-failure
```

For the GPU implementation, use CUDA 12.8 and an Ada GPU that supports
cooperative launch. The build targets native `sm_89`.

```sh
cmake -S . -B build/gpu -DCOOPSBR_ENABLE_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build/gpu --parallel
ctest --test-dir build/gpu --output-on-failure
```

For example, run the sequential and cooperative solvers on the same
human–chimpanzee block order. The checker replays the GPU trace independently.

```sh
input=datasets/comparisons/ucsc-anchors-v1/hg38-panTro6-chr1-min250.txt
build/cpu/coopsbr --input "$input" --trace build/seq.trace --mode seq
build/gpu/coopsbr --input "$input" --trace build/gpu.trace --mode gpu-full \
  --update full --coord cooperative-fused-changed --candidate local \
  --reduction scalar --threads 128
build/cpu/coopsbr-check "$input" build/gpu.trace
cmp build/seq.trace build/gpu.trace
```

The other main GPU protocols use `--coord graph`,
`--coord cooperative-replicated`, and `--coord cooperative-fused-full`
with the same full-update, local-candidate, and scalar-reduction settings.

## Data, results, and proofs

- [Artifact guide](ARTIFACT.md) and [input documentation](datasets/README.md)
- [Synthetic and Drosophila timing records and paired summaries](reports/fused-update-main-20261120/)
- [Human–chimpanzee timing records, paired summaries, and repeat](reports/ucsc-anchors-20261121/)
- [Human–chimpanzee inputs and reference traces](datasets/comparisons/ucsc-anchors-v1/)
- [Paired CPU–GPU timings and Figure 3](reports/paired-cpu-gpu-20261121/)
- [Graph reuse and matched barrier controls](reports/graph-barrier-study-20261121/)
- [Approximation proof](docs/APPROXIMATION_PROOF.md) and
  [GPU trace-equivalence proof](docs/PARALLEL_CORRECTNESS_THEOREM.md)

To reproduce Figure 2 from the archived results, install Matplotlib and
run `python3 manuscript/plot_protocol_comparison.py` from the repository root.

The [CPU–GPU benchmark guide](reports/paired-cpu-gpu-20261121/) describes how to recompute
its summaries and redraw Figure 3.
