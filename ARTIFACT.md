# CoopSbR research archive

This archive supports the manuscript *CoopSbR: Trace-preserving GPU sorting of
unsigned permutations by reversals*. The archived timing records correspond to
the NVIDIA RTX 6000 Ada Generation platform, CUDA 12.8.1, and the solver
revision identified in the archive manifest.

## Inputs and results

- The synthetic and Drosophila paired comparison uses inputs in
  datasets/comparisons/graph-size-sweep-v1 and datasets/comparisons/graph-v1.
  The six fly gene orders and their annotation mappings are also in
  datasets/real/v1.
- The six human–chimpanzee alignment-derived permutations and sequential
  certificates are in datasets/comparisons/ucsc-anchors-v1. The manifest pins the
  upstream UCSC data, input checksums, and trace checksums. The generator is
  scripts/prepare_chain_inputs.py.
- Per-call timings, paired summaries and binary provenance are in
  reports/fused-update-main-20261120 and reports/ucsc-anchors-20261121. The latter
  also archives the repeat.
- The [paired CPU–GPU benchmark](reports/paired-cpu-gpu-20261121/)
  contains the measurements, solver driver and Figure 3 data.
- The [Graph reuse and barrier study](reports/graph-barrier-study-20261121/)
  contains the 12-mode measurements, timing components, amortization
  batches, analysis tables and source files for the matched GPU controls.
- [Fused GPU validation](reports/fused-update-pilot-20261120/VALIDATION.md)
  records the test and sanitizer coverage. The runner uses the archived
  pilot binary hashes and [Drosophila trace certificates](reports/graph-reference-20261118/per-input.csv).

## Build and check

Configure CMake with COOPSBR_ENABLE_CUDA=OFF for the sequential solver
and checker. The GPU implementations require a CUDA 12.8 toolchain, a GPU
supporting the compiled CUDA architecture, and a supported cooperative launch.
The default CUDA target is native sm_89 for the measured Ada GPU.

    cmake -S . -B build/cpu -DCOOPSBR_ENABLE_CUDA=OFF -DCMAKE_BUILD_TYPE=Release
    cmake --build build/cpu
    ctest --test-dir build/cpu --output-on-failure

Run the replay checker on a saved permutation and reference trace.

    build/cpu/coopsbr-check datasets/comparisons/ucsc-anchors-v1/hg38-panTro6-chr1-min250.txt datasets/comparisons/ucsc-anchors-v1/hg38-panTro6-chr1-min250.trace

The archived GPU runner records the Git revision and checks the hashes of the
original binaries. Independently rebuilt binaries can be run per input using
the executable's command-line options in the captured run configuration.
Compare the completed reversal trace with the per-input SHA-256 certificate.
A rerun on a different build or GPU will yield a distinct timing measurement.

To redraw Figure 2, install Matplotlib and run
python3 manuscript/plot_protocol_comparison.py from the archive root. The [CPU–GPU benchmark guide](reports/paired-cpu-gpu-20261121/)
gives the Figure 3 commands.
The original genome annotations and alignments are linked in the dataset
manifests and source locks. The archive contains the derived input permutations.
