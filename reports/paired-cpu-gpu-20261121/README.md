# Paired CPU–GPU benchmark

The benchmark pairs the single-threaded C++ reference with the fused
changed-interval GPU mode on 70 synthetic and 12 genomic inputs. All are
listed in `cases.json` with their archive paths and expected checksums.
The warmed wall time includes work and transfers from the host input to the
returned host results. Both implementations use the same timing boundary.

- `raw-results.tar.gz` contains the measurement design, build provenance,
  solver settings and trace verification records for all 142 paired rounds.
- `analysis/per-input.csv` and `analysis/synthetic-cells.csv` contain the
  ratios behind Figure 3. `analysis/paired-rounds.csv` gives the round medians.
- `timed_main.cpp` adds the shared timing boundary to the CLI in solver
  revision `dcdc2fde817957b176d3978c7fa9e7d8a0318b24`. `run_paired.py` runs
  the pairs and replays every trace. The build below uses the public base tree and the
  benchmark driver archived here. Input paths are relative to the repository root.

From the archive root, recompute all numerical summaries in a new directory.

```sh
mkdir paired-raw
benchmark=reports/paired-cpu-gpu-20261121
tar -xzf "$benchmark/raw-results.tar.gz" -C paired-raw
python3 "$benchmark/analyze_paired.py" --manifest "$benchmark/cases.json" \
  --results paired-raw --out paired-recomputed
Rscript manuscript/plot_paired_cpu_gpu.R paired-recomputed cpu-gpu-paired-comparison.pdf
```

## Build and run

From the repository root, with the CUDA 12.8 toolkit, a compatible GCC,
CMake, Ninja and an RTX 6000 Ada available:

```sh
repo=$(git rev-parse --show-toplevel)
benchmark="$repo/reports/paired-cpu-gpu-20261121"
scratch=$(mktemp -d)
mkdir "$scratch/source"
git archive 87d73a52b8e187720ef1156b3c21dad07061767e CMakeLists.txt include src tests | tar -x -C "$scratch/source"
cp "$benchmark/timed_main.cpp" "$scratch/source/src/main.cpp"
cmake -S "$scratch/source" -B "$scratch/build" -G Ninja \
  -DCOOPSBR_ENABLE_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build "$scratch/build" --target coopsbr coopsbr-check
CUDA_DISABLE_PTX_JIT=1 python3 "$benchmark/run_paired.py" \
  --manifest "$benchmark/cases.json" --inputs "$repo" --out "$scratch/run" \
  --binary "$scratch/build/coopsbr" --checker "$scratch/build/coopsbr-check"
```
