# Real gene-order corpus v1

The inputs are unsigned gene-order permutations from public nuclear genomes,
with one chromosome arm per problem. They are not DNA strings or simulated
biological data. Annotation, orthology and assembly records are fixed by
[source-lock.json](source-lock.json).

| Species | Assembly accession | Annotation snapshot |
| --- | --- | --- |
| D. melanogaster | GCA_000001215.4, BDGP6.54 | FlyBase dmel_r6.54_FB2023_05 imported into Ensembl Metazoa 63 |
| D. simulans (w501) | GCA_016746395.2, Prin_Dsim_3.1 | PrinDsim3v1.0, Ensembl Metazoa 63 |
| D. yakuba (Tai18E2) | GCA_016746365.2, Prin_Dyak_Tai18E2_2.1 | PrinDyakTai18E22v1.0, Ensembl Metazoa 63 |

All orthology records use Ensembl Compara 116, the
`protein_pangenome_drosophila` gene-tree collection. Both species-specific dumps
are combined: the provider explains that each contains only a complementary
subset of relationships. Exact duplicate relationships are collapsed; conflicts
are errors. Orthology is taken from the provider, not inferred from gene names
or from the observed sorting result.

## Selected inputs

| Case | Retained markers n |
| --- | --- |
| dmel-dsim-3R | 3109 |
| dmel-dsim-2R | 2565 |
| dmel-dsim-3L | 2505 |
| dmel-dyak-3R | 3060 |
| dmel-dyak-3L | 2415 |
| dmel-dyak-X | 1890 |

[The manifest](v1/manifest.json) identifies all six inputs and their hashes.
`mapping.tsv` contains full reference/query coordinates and strands;
`permutation.txt` is the actual solver input. Each case also retains its supplied
orthology table, rejected pairs, and provenance. [candidates.tsv](v1/candidates.tsv)
reports all ten examined arm candidates and every exclusion; the complete
cross-chromosome counts are in [chromosome-matrix.tsv](v1/chromosome-matrix.tsv).

## Filtering and representation

1. Keep only `ortholog_one2one` relationships with provider
   `is_high_confidence=1`. Require a unique partner across the reported
   cross-species relationships, and one annotated gene-feature locus for each
   gene ID. This is an operational single-copy marker definition, not an
   independent sequence copy-number analysis.
2. Normalize Ensembl GFF3 IDs with the `gene_id` attribute (or `ID` after removal
   of its `gene:` prefix). Validate the annotation's assembly accession and all
   gene bounds against GFF3 sequence-region headers.
3. Match named nuclear arms using NCBI assembly sequence reports. The query GFF3
   uses GenBank sequence accessions; their lengths must match the named NCBI
   chromosomes. No unrelated arms or chromosomes are concatenated.
4. Examine 2L,2R,3L,3R,X. Arm fidelity is the fraction of reliable reference-arm
   orthologs located on the corresponding query arm, before coordinate filtering.
   Require fidelity >=90%. Dyak 2L and 2R fail this criterion (about 79% and 76%);
   they are not forced into a within-arm-only rearrangement interpretation.
5. Keep only markers present in the selected arm in both genomes. Exclude the
   entire group whenever retained reference or query starts are identical.
   This removes an arbitrary gene-ID ordering of coordinate ties. Every removed
   pair is recorded. The final mappings have unique starts in both genomes.
6. Require at least 1,024 markers after filtering, then choose the three largest
   eligible arms per comparison, breaking size ties by arm name. These rules and
   the six-case budget were fixed before performance measurements. Other eligible
   Dsim arms are listed as unselected for the declared case-count budget.
7. Sort genes by increasing genomic start coordinate and label by reference
   order. Query order becomes a permutation of 1..n. Gene orientation is ignored;
   the supplied assembly orientation is used without optimizing it for speedup.

Provider high-confidence calls use evidence that can include gene-order
conservation and alignments. The corpus therefore represents curated conserved
markers, not an unbiased sample of all genes or rearrangements. Overlapping
loci with different starts are ordered by their leftmost genomic coordinate;
only identical starts are removed. Annotation/model differences and excluded
cross-arm relationships limit evolutionary interpretation. An unsigned reversal
trace is not a reconstructed biological history.

## Rebuild and verify

```bash
python3 scripts/prepare_real_corpus.py --out data/recreated-real
python3 scripts/validate_corpus.py --manifest data/recreated-real/manifest.json
```

The preparation script downloads only checksum-pinned source bytes (or reuses
matching cached files), checks accession/coordinate correspondence, and refuses
a nonempty output directory. The nine raw inputs total about 29 MB. All output
paths are relative, so no workstation connection settings are embedded in this
corpus. A complete byte-for-byte rebuild was checked. Validation reconstructs
permutations independently from the published coordinate mapping and verifies
saved hashes. [VALIDATION.json](VALIDATION.json) contains the input integrity
results, not algorithm performance measurements. Independently replayed
[solution certificates](solutions/checks.json) are also saved; see the
[preparation validation report](../../docs/PREPARATION_VALIDATION.md).

## Sources and attribution

- [Ensembl Metazoa release 63 files](https://ftp.ebi.ac.uk/ensemblgenomes/pub/metazoa/release-63/)
- [Compara dump format and completeness notes](https://ftp.ebi.ac.uk/ensemblgenomes/pub/metazoa/release-63/tsv/ensembl-compara/homologies/README.gene_trees.tsv_dumps.txt)
- [Ensembl homology types and confidence](https://www.ensembl.org/info/genome/compara/homology_types.html)
- [NCBI sequence reports API](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/reference-docs/rest-api/)
- [FlyBase source annotation](https://flybase.org/downloads/bulkdata)

Credit Ensembl/EMBL-EBI, FlyBase and NCBI plus the referenced genome assemblies
when using these derived inputs. Exact download URLs, annotation names, file
sizes and SHA-256 values are in the source lock.
