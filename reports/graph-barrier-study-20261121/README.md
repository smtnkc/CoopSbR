# Graph reuse and barrier controls

The full matched GPU study covers 82 inputs and 12 modes. It compares fresh
and preinstantiated conditional Graphs, fresh and persistent device
workspaces, and cooperative controls for publication and fusion. The
archive includes the verified per-call measurements, recorded method
orders, pilot replay checks, direct 1/10/100-call amortization runs, and
build provenance. The CUDA validation summary is in `validation.txt`.

## Analyze the archived run

From the repository root:

```sh
study=reports/graph-barrier-study-20261121
work=$(mktemp -d)
mkdir "$work/raw"
tar -xzf "$study/raw-results.tar.gz" -C "$work/raw"
python3 "$study/analyze_experiments.py" --manifest "$study/cases.json" \
  --results "$work/raw" --out "$work/analysis"
diff -r "$study/analysis" "$work/analysis"
```

## Build and measure

The tested build starts from the solver revision recorded in `cases.json`.
The public release commit below carries the same CMake, source, header and
test files used to build the benchmark. The three replacement files under
`patch/` add the matched kernels and persistent execution modes.

From the repository root, with CUDA 12.8, GCC, CMake, Ninja and an RTX 6000 Ada:

```sh
repo=$(git rev-parse --show-toplevel)
study="$repo/reports/graph-barrier-study-20261121"
scratch=$(mktemp -d)
mkdir "$scratch/source"
git archive 87d73a52b8e187720ef1156b3c21dad07061767e CMakeLists.txt include src tests | tar -x -C "$scratch/source"
cp -R "$study/patch/." "$scratch/source/"
cmake -S "$scratch/source" -B "$scratch/build" -G Ninja \
  -DCOOPSBR_ENABLE_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build "$scratch/build" --target coopsbr coopsbr-check
cp "$study/cases.json" "$scratch/"
ln -s "$repo" "$scratch/inputs"
CUDA_DISABLE_PTX_JIT=1 python3 "$study/run_experiments.py" "$scratch"
```

New runs can use the analysis script with `--results "$scratch/results"`.
