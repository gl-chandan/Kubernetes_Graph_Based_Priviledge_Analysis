#!/usr/bin/env python3
"""Compare graph analysis with existing baseline methods on rendered Helm charts."""

import csv
from pathlib import Path

from analyzer.baseline import flat_review, single_step_lint
from analyzer.graph import build_graph, entry_points
from analyzer.paths import enumerate_paths, flagged_entries
from analyzer.snapshot import Cluster

CHARTS = [
    "prometheus",
    "alertmanager",
    "ingress-nginx",
    "kube-state-metrics",
    "memcached",
    "nginx",
    "postgresql",
    "prometheus-node-exporter",
    "rabbitmq",
    "redis",
]
MAX_HOPS = 4
OUT = Path("results/helm")
OUT.mkdir(parents=True, exist_ok=True)


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    comparison_rows = []
    missed_rows = []

    for chart in CHARTS:
        snapshot_dir = Path("data/helm_snapshots") / chart
        cluster = Cluster.from_dir(str(snapshot_dir))
        graph, _ = build_graph(cluster)
        entries = entry_points(graph)
        paths = enumerate_paths(graph, entries, MAX_HOPS)

        results = {
            "Flat review (emulated)": flat_review(graph, entries),
            "Single-step lint": single_step_lint(graph, entries),
            "Graph (this work)": flagged_entries(paths),
        }

        graph_entries = results["Graph (this work)"]
        print(
            f"{chart:30} nodes={graph.number_of_nodes():3} "
            f"edges={graph.number_of_edges():3} "
            f"entries={len(entries):3} "
            f"graph_flagged={len(graph_entries):3}"
        )

        for method, flagged in results.items():
            comparison_rows.append({
                "chart": chart,
                "method": method,
                "entry_points": len(entries),
                "flagged_entries": len(flagged),
                "max_hops": MAX_HOPS,
            })

        # Report graph paths whose entry point was not flagged by a baseline.
        for path in paths:
            for baseline_name in (
                "Flat review (emulated)",
                "Single-step lint",
            ):
                if path.entry not in results[baseline_name]:
                    missed_rows.append({
                        "chart": chart,
                        "baseline": baseline_name,
                        "entry": path.entry,
                        "hops": path.hops,
                        "total_cost": path.cost,
                        "exploitability_score": path.score,
                        "path": " -> ".join(path.nodes),
                    })

    write_csv(
        OUT / "o4_baseline_comparison.csv",
        comparison_rows,
        ["chart", "method", "entry_points", "flagged_entries", "max_hops"],
    )
    write_csv(
        OUT / "o4_missed_paths.csv",
        missed_rows,
        [
            "chart", "baseline", "entry", "hops", "total_cost",
            "exploitability_score", "path",
        ],
    )

    print(f"\nSaved {OUT / 'o4_baseline_comparison.csv'}")
    print(f"Saved {OUT / 'o4_missed_paths.csv'}")
    print(f"Graph paths not flagged by a baseline: {len(missed_rows)}")
    print("Note: these are modeled paths from rendered templates, not confirmed exploits.")


if __name__ == "__main__":
    main()
