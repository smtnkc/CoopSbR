# Large-input extension corpus

A separate seed-42 MT19937 stream generated 24 pilot and 120 main inputs in the
recorded order. Sizes are 32,768, 65,536 and 131,072; semi-random k is 4,64,1024.
There are two pilot and ten main files per cell. All saved hashes are distinct;
the input lengths also distinguish this corpus from v1. This corpus continues
the study with a separately declared workload; its results never replace v1.

Generated locally using scripts/generate_inputs.py; Python version and hashes
are in manifest.json. scripts/validate_corpus.py passed on all 144 inputs and
independently replayed every semi-random construction trace. Reuse saved bytes
across implementations. No reset of the random stream occurs between instances.
The k value is a generating parameter, not optimum reversal distance.
