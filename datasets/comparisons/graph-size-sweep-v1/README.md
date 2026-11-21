# Seven-size Graph/cooperative sweep

Sizes: 2048,4096,8192,16384,32768,65536,131072. Uniform and semi-random k=64;
five distinct main files and two separate pilot files per cell. All seven sizes
are measured in the same new campaign with the existing identical solver binary.
Main input pairs are shuffled across lengths with seed 42; methods remain
adjacent within each pair. Pilot sizes remain ascending for feasibility checks.

Only the previously absent n=2048 and 8192 files were generated, using one new
recorded seed-42 stream. Other input bytes are reused without alteration. The
source manifests, paths and hashes record all choices. No selection uses the
new timing results. New inputs have independent local sequential/replay trace
certificates; existing inputs reuse archival certificates. Both methods must
match those certificates as well as one another.

Main: 70 inputs x 2 methods x (one warm-up + three measurements) = 560 calls.
Pilot: 28 inputs x 2 methods x (one warm-up + two measurements) = 168 calls.
Prior real-input results remain unchanged; this extension studies synthetic
size effects and does not repeat or enlarge the biological corpus.
