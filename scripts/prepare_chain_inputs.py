"""Prepare the six UCSC human–chimpanzee alignment-block inputs for CoopSbR."""

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import subprocess


SOURCE = (
    "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/vsPanTro6/"
    "reciprocalBest/hg38.panTro6.rbest.chain.gz"
)
SOURCE_SHA256 = "d8f87136a8788fcd01995448b693484957bf86d8e9e4efe653c67dba81248f5e"
CHROMOSOMES = ("chr1", "chr16")
THRESHOLDS = (100, 250, 500)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_blocks(path):
    """Collect same-chromosome blocks and all >=100 bp intervals on either axis."""
    blocks = defaultdict(list)
    target_intervals = defaultdict(list)
    query_intervals = defaultdict(list)
    with gzip.open(path, "rt") as stream:
        for line in stream:
            row = line.split()
            if not row:
                continue
            if row[0] == "chain":
                _, _, target, _, t_strand, t_start, t_end, query, q_size, q_strand, q_start, q_end, _ = row
                relevant = target in CHROMOSOMES or query in CHROMOSOMES
                if relevant:
                    if t_strand != "+" or q_strand not in ("+", "-"):
                        raise ValueError("Unexpected chain orientation")
                    t_pos, q_pos = int(t_start), int(q_start)
                    t_limit, q_limit, q_size = int(t_end), int(q_end), int(q_size)
                continue
            if not relevant:
                continue
            size = int(row[0])
            if size >= THRESHOLDS[0]:
                q_forward = q_pos if q_strand == "+" else q_size - q_pos - size
                index = -1
                if target == query:
                    index = len(blocks[target])
                    blocks[target].append((t_pos, q_forward, size))
                if target in CHROMOSOMES:
                    target_intervals[target].append((t_pos, size, index))
                if query in CHROMOSOMES:
                    query_intervals[query].append((q_forward, size, index))
            t_pos += size
            q_pos += size
            if len(row) == 3:
                t_pos += int(row[1])
                q_pos += int(row[2])
            elif len(row) != 1 or t_pos != t_limit or q_pos != q_limit:
                raise ValueError("Block positions do not match the chain header")
    return blocks, target_intervals, query_intervals


def overlapping(intervals):
    """Return the indices of blocks that intersect another interval on this axis."""
    rejected = set()
    furthest_end = -1
    furthest_index = -1
    for start, length, index in sorted(intervals):
        if start < furthest_end:
            rejected.update((index, furthest_index))
        if start + length > furthest_end:
            furthest_end = start + length
            furthest_index = index
    return rejected


def prepare(chain, out, binary, checker):
    digest = sha256(chain)
    if digest != SOURCE_SHA256:
        raise ValueError("The chain archive does not match the study snapshot")
    blocks, target, query = read_blocks(chain)
    out.mkdir()
    cases = []
    for chromosome in CHROMOSOMES:
        rejected = overlapping(target[chromosome]) | overlapping(query[chromosome])
        retained = sorted(block for i, block in enumerate(blocks[chromosome]) if i not in rejected)
        for cutoff in THRESHOLDS:
            query_starts = [q_start for _, q_start, length in retained if length >= cutoff]
            permutation = sorted(range(1, len(query_starts) + 1), key=lambda i: query_starts[i - 1])
            case_id = f"hg38-panTro6-{chromosome}-min{cutoff}"
            path = out / f"{case_id}.txt"
            trace = out / f"{case_id}.trace"
            path.write_bytes(f"{len(permutation)}\n{' '.join(map(str, permutation))}\n".encode("ascii"))
            measured = json.loads(subprocess.check_output([
                str(binary), "--mode", "seq", "--input", str(path), "--trace", str(trace),
            ], text=True, timeout=60))
            checked = json.loads(subprocess.check_output([
                str(checker), str(path), str(trace),
            ], text=True, timeout=60))
            if not checked["verified"] or checked["reversals"] != measured["reversals"]:
                raise ValueError(f"Sequential trace failed replay: {case_id}")
            cases.append({
                "id": case_id, "family": "real", "chromosome": chromosome,
                "min_block_bp": cutoff, "primary": cutoff == 250, "n": len(permutation),
                "initial_breakpoints": measured["initial_breakpoints"],
                "reversals": measured["reversals"], "path": path.name,
                "sha256": sha256(path), "trace_path": trace.name, "trace_sha256": sha256(trace),
            })
            print(case_id, measured["n"], measured["initial_breakpoints"], measured["reversals"])
    manifest = {
        "dataset": "hg38-panTro6-chr1-chr16-v1",
        "source_url": SOURCE,
        "source_sha256": digest,
        "coordinate_convention": "0-based half-open on both forward strands",
        "overlap_filter_bp": THRESHOLDS[0],
        "cases": cases,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chain", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--checker", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.chain, args.out, args.binary.resolve(), args.checker.resolve())
