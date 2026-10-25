#!/usr/bin/env python3
"""Repeated experiments and descriptive statistics for Review 3."""

import csv
import math
import statistics
import time
from pathlib import Path

from analyzer.paths import enumerate_paths, flagged_entries
from analyzer.synthetic import (
    cluster_size_variant,
    expected_flagged,
    make_cluster,
)
from run_experiments import (
    K3S_HOPS,
    SYN_HOPS,
    chain_found,
    prepare,
)
from analyzer.baseline import flat_review, single_step_lint

OUT = Path("results/review3_corrected")
OUT.mkdir(parents=True, exist_ok=True)

# For n=3, the two-sided 95% Student-t critical value with 2 df is 4.303.
T_CRITICAL_N3 = 4.303
REPEATS = 3
SEEDS = (101, 202, 303)


def summarize(values):
    """Return mean, sample variance, standard deviation, and 95% t interval."""
    mean = statistics.mean(values)
    variance = statistics.variance(values) if len(values) > 1 else 0.0
    sd = math.sqrt(variance)
    margin = T_CRITICAL_N3 * sd / math.sqrt(len(values)) if len(values) == 3 else float("nan")
    return {
        "runs": len(values),
        "mean": mean,
        "sample_variance": variance,
        "sample_stddev": sd,
        "ci95_low": mean - margin,
        "ci95_high": mean + margin,
    }


def save_csv(filename, rows):
    if not rows:
        print(f"No rows to write for {filename}")
        return
    with (OUT / filename).open("w", newline="", encoding="utf-8") as f:
        fieldnames = list(dict.fromkeys(
            key for row in rows for key in row.keys()
        ))
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {OUT / filename}")


def repeated_planted_validation():
    """Repeat each chain-length configuration with three different seeds."""
    raw_rows = []

    for length in (1, 2, 3, 4, 5):
        for seed in SEEDS:
            raw, truth = make_cluster(
                (length,), 8, n_noise_ns=10, seed=seed
            )
            graph, entries = prepare(raw)
            paths = enumerate_paths(graph, entries, SYN_HOPS)

            methods = {
                "Flat review (emulated)": flat_review(graph, entries),
                "Single-step lint": single_step_lint(graph, entries),
                "Graph (this work)": flagged_entries(paths),
            }

            expected = expected_flagged(truth)

            planted = len(truth["chains"])

            for method, found in methods.items():
                # Common metric: did the method flag the chain's first SA?
                recovered = sum(
                    chain["subjects"][0] in found
                    for chain in truth["chains"]
                )

                # Graph-specific metric: exact ordered-chain recovery.
                exact_recall = ""
                if method == "Graph (this work)":
                    exact_recovered = sum(
                        chain_found(graph, paths, chain)
                        for chain in truth["chains"]
                    )
                    exact_recall = (
                        exact_recovered / planted if planted else 0.0
                    )

                raw_rows.append({
                    "chain_length": length,
                    "seed": seed,
                    "method": method,
                    "planted_chains": planted,
                    "recovered_entrypoints": recovered,
                    "entrypoint_recall": (
                        recovered / planted if planted else 0.0
                    ),
                    "exact_chain_recall": exact_recall,
                    "flagged_entries": len(found),
                    "false_positive_entries": len(found - expected),
                })

    save_csv("planted_validation_runs.csv", raw_rows)

    grouped = {}
    for row in raw_rows:
        key = (row["chain_length"], row["method"])
        grouped.setdefault(key, []).append(row)

    summary_rows = []
    for (length, method), rows in sorted(grouped.items()):
        result = {
            "chain_length": length,
            "method": method,
            "runs": len(rows),
        }
        for metric in ("entrypoint_recall", "flagged_entries", "false_positive_entries"):
            stats = summarize([float(r[metric]) for r in rows])
            for stat_name, value in stats.items():
                if stat_name != "runs":
                    result[f"{metric}_{stat_name}"] = value
        if method == "Graph (this work)":
            stats = summarize([
                float(r["exact_chain_recall"]) for r in rows
            ])
            for stat_name, value in stats.items():
                if stat_name != "runs":
                    result[f"exact_chain_recall_{stat_name}"] = value

        summary_rows.append(result)

    save_csv("planted_validation_summary.csv", summary_rows)
    print("\nEntry-point recall summary (three seeds):")
    for row in summary_rows:
        print(
            f'length={row["chain_length"]} '
            f'{row["method"]}: '
            f'entrypoint_recall_mean={row["entrypoint_recall_mean"]:.3f}, '
            f'variance={row["entrypoint_recall_sample_variance"]:.5f}'
        )


def repeated_runtime():
    """Measure graph construction and path enumeration three times per size."""
    raw_rows = []

    for size in (50, 100, 200, 400, 800, 1600, 3200):
        raw, _ = cluster_size_variant(size, seed=5)

        for repeat in range(1, REPEATS + 1):
            start = time.perf_counter()
            graph, entries = prepare(raw)
            build_seconds = time.perf_counter() - start

            start = time.perf_counter()
            paths = enumerate_paths(graph, entries, SYN_HOPS)
            enumerate_seconds = time.perf_counter() - start

            raw_rows.append({
                "requested_size": size,
                "repeat": repeat,
                "graph_nodes": graph.number_of_nodes(),
                "graph_edges": graph.number_of_edges(),
                "entry_points": len(entries),
                "build_seconds": build_seconds,
                "enumerate_seconds": enumerate_seconds,
                "total_seconds": build_seconds + enumerate_seconds,
                "paths_found": len(paths),
            })

    save_csv("runtime_runs.csv", raw_rows)

    summary_rows = []
    for size in sorted({row["requested_size"] for row in raw_rows}):
        rows = [r for r in raw_rows if r["requested_size"] == size]
        result = {
            "requested_size": size,
            "graph_nodes": rows[0]["graph_nodes"],
            "graph_edges": rows[0]["graph_edges"],
            "entry_points": rows[0]["entry_points"],
            "paths_found": rows[0]["paths_found"],
        }
        for metric in ("build_seconds", "enumerate_seconds", "total_seconds"):
            for stat_name, value in summarize([r[metric] for r in rows]).items():
                if stat_name != "runs":
                    result[f"{metric}_{stat_name}"] = value
        result["runs"] = len(rows)
        summary_rows.append(result)

    save_csv("runtime_summary.csv", summary_rows)
    print("\nRuntime summary (seconds; mean and sample variance):")
    for row in summary_rows:
        print(
            f'size={row["requested_size"]:4} '
            f'nodes={row["graph_nodes"]:5} '
            f'total_mean={row["total_seconds_mean"]:.5f} '
            f'total_variance={row["total_seconds_sample_variance"]:.8f}'
        )


if __name__ == "__main__":
    repeated_planted_validation()
    repeated_runtime()
    print("\nReview 3 repeated experiments complete.")
