# Human–chimpanzee alignment-block comparison

The alignment-block evaluation uses two homologous chromosome pairs from the UCSC human
GRCh38 and chimpanzee Clint_PTRv2 reciprocal-best chain archive. The
250 bp minimum was selected during input inspection to cover lengths
below and above the upper end of the synthetic study. The 100 and
500 bp settings use different encodings of the same chromosome pairs.

The generator uses gap-free blocks, excludes interval overlaps on
either axis across the blocks of at least 100 bp, and retains matching
chromosomes. It converts chimpanzee coordinates to the forward strand
and assigns labels in human coordinate order. The [manifest](manifest.json)
pins the public source, the six input hashes and their reference trace hashes.

## Timings

Graph, C4, F and CI are conditional CUDA Graph, the four-barrier
cooperative method, fused full copy and fused changed intervals.
The four timing columns are first-sweep end-to-end medians in ms.

| Chr. | Min. bp | Markers | Reversals | Graph | C4 | F | CI | Repeat C4/CI |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| chr1 | 100 | 255,924 | 296 | 6.8426 | 6.5735 | 4.8236 | 4.6788 | 1.400 |
| chr1 | **250** | 203,698 | 192 | 4.4203 | 3.3688 | 3.1010 | 3.0313 | 1.115 |
| chr1 | 500 | 141,617 | 123 | 2.4791 | 1.7793 | 1.6199 | 1.5784 | 1.144 |
| chr16 | 100 | 91,158 | 242 | 3.8443 | 2.5880 | 2.3199 | 2.2330 | 1.158 |
| chr16 | **250** | 70,726 | 135 | 2.0356 | 1.3206 | 1.2362 | 1.2110 | 1.116 |
| chr16 | 500 | 47,804 | 88 | 1.3860 | 0.9056 | 0.8730 | 0.8517 | 1.020 |

First-sweep speedups of CI were 1.458--1.722× over Graph,
1.063--1.405× over C4, and 1.021--1.039× over F. The repeat had
the same direction on all six inputs against each comparator.
Repeat speedups were 1.460--1.728×, 1.020--1.400× and
1.017--1.058×, respectively. Changed intervals reduced the
logical permutation store count by 78.6--96.7% including initialization.
The two sweeps are reported separately.

## Reproduction

The runs used the same GPU, solver and checker as the
[synthetic and Drosophila comparison](../fused-update-main-20261120/REPORT.md).
Both sweeps used seed 42 for paired ordering, one warm-up and three
timed calls per input and method. All 192 GPU traces, including warm-ups,
matched the sequential SHA-256 certificate and passed independent
replay. The provenance files retain the binary, manifest and runner hashes.

Download the [UCSC chain snapshot](https://hgdownload.soe.ucsc.edu/goldenPath/hg38/vsPanTro6/reciprocalBest/hg38.panTro6.rbest.chain.gz)
to regenerate the input permutations. Run the following command from the
repository root after building the sequential solver and checker.

```sh
python3 scripts/prepare_chain_inputs.py hg38.panTro6.rbest.chain.gz \
  runs/ucsc-inputs --binary build/cpu/coopsbr --checker build/cpu/coopsbr-check
```

Compare the generated manifest with the
[archived input manifest](../../datasets/comparisons/ucsc-anchors-v1/manifest.json).
For an independently built solver, use the [per-input commands](../../README.md#build-and-verify)
with the archived method order and one warm-up followed by three timed calls.
The archived campaign runner checks for the original validated binary hashes.
The timing records and paired summaries cover both the initial sweep and the repeat.
