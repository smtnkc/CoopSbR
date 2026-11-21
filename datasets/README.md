# Experiment inputs

The manuscript timings use the following comparison inputs. Each GPU protocol
uses the same saved permutation for a given case.

| Corpus | Files | Manuscript coverage |
| --- | --- | --- |
| Uniform and semi-random synthetic | [Seven-size sweep](comparisons/graph-size-sweep-v1/) | 70 main cases |
| Drosophila chromosome-arm gene orders | [Graph comparison inputs](comparisons/graph-v1/) | 6 cases |
| Human–chimpanzee alignment block orders | [Input and trace manifest](comparisons/ucsc-anchors-v1/manifest.json) | 6 cases |

## Initial experiment corpora

| Corpus | Manifest | Cases |
| --- | --- | --- |
| Uniform and semi-random synthetic | [synthetic/v1/manifest.json](synthetic/v1/manifest.json) | 24 pilot + 120 main |
| Real Drosophila gene orders | [real/v1/manifest.json](real/v1/manifest.json) | 6 |

The initial synthetic grid uses n=1024,4096,16384 and k=4,64,1024 for semi-random
inputs.
The prepared real corpus is fixed by annotation quality and retained marker
counts, independently of sorting times or speedups.

See [real-data methods and provenance](real/README.md),
[synthetic generation](synthetic/README.md), and
[the approximation proof](../docs/APPROXIMATION_PROOF.md).

```bash
python3 scripts/validate_corpus.py --manifest datasets/synthetic/v1/manifest.json
python3 scripts/validate_corpus.py --manifest datasets/real/v1/manifest.json
```

Real mapping files allow the query permutation to be reconstructed independently
from coordinates. Synthetic construction traces can be replayed from identity.
Source hashes, filtering decisions, and all eligible/unselected chromosome-arm
candidates are retained. Large raw source downloads are cached under ignored
`data/raw/ensembl63`; the 9 pinned input URLs total about 29 MB and can be fetched
again by the preparation script. Genomic DNA FASTA is not needed for this
annotation-based gene-order representation; assembly accessions and sequence
bounds are verified against official records.
