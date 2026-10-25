#!/usr/bin/env python3
"""Convert rendered Helm YAML into the analyzer's JSON snapshot format."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import yaml

KIND_FILES = {
    "ServiceAccount": "serviceaccounts",
    "Role": "roles",
    "ClusterRole": "clusterroles",
    "RoleBinding": "rolebindings",
    "ClusterRoleBinding": "clusterrolebindings",
    "Pod": "pods",
    "Namespace": "namespaces",
}

NAMESPACED_KINDS = {
    "ServiceAccount",
    "Role",
    "RoleBinding",
    "Pod",
}

WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}


def convert(manifest_path, output_dir, release_namespace):
    manifest_path = Path(manifest_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    resources = defaultdict(list)
    total_documents = 0

    with manifest_path.open(encoding="utf-8") as stream:
        for obj in yaml.safe_load_all(stream):
            if not isinstance(obj, dict):
                continue

            total_documents += 1
            kind = obj.get("kind")
            if kind not in KIND_FILES and kind not in WORKLOAD_KINDS:
                continue

            metadata = obj.get("metadata") or {}

            # Add the release namespace only to namespaced resource kinds.
            # ClusterRoles and ClusterRoleBindings must remain cluster-scoped.
            if kind in NAMESPACED_KINDS and not metadata.get("namespace"):
                metadata["namespace"] = release_namespace
                obj["metadata"] = metadata

            if kind in KIND_FILES:
                resources[KIND_FILES[kind]].append(obj)

            # Analyze workload pod templates as synthetic Pods.
            # These represent rendered templates, not confirmed running Pods.
            if kind in WORKLOAD_KINDS:
                if kind == "CronJob":
                    pod_spec = (
                        obj.get("spec", {})
                        .get("jobTemplate", {})
                        .get("spec", {})
                        .get("template", {})
                    )
                else:
                    pod_spec = obj.get("spec", {}).get("template", {})

                template_metadata = pod_spec.get("metadata") or {}
                template_spec = pod_spec.get("spec") or {}

                if template_spec:
                    pod_name = metadata.get("name", kind.lower())
                    pod_namespace = metadata.get("namespace", release_namespace)
                    synthetic_pod = {
                        "apiVersion": "v1",
                        "kind": "Pod",
                        "metadata": {
                            "name": f"{pod_name}-template",
                            "namespace": pod_namespace,
                            "labels": template_metadata.get("labels") or {},
                        },
                        "spec": template_spec,
                    }
                    resources["pods"].append(synthetic_pod)

    for filename in KIND_FILES.values():
        payload = {
            "apiVersion": "v1",
            "kind": "List",
            "items": resources[filename],
        }
        (output_dir / f"{filename}.json").write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"Manifest: {manifest_path}")
    print(f"Documents read: {total_documents}")
    print(f"Snapshot directory: {output_dir}")
    print(f"Release namespace: {release_namespace}")
    for filename in KIND_FILES.values():
        print(f"{filename}: {len(resources[filename])}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="Rendered Helm YAML file")
    parser.add_argument("output", help="Output snapshot directory")
    parser.add_argument(
        "--namespace",
        required=True,
        help="Namespace used when rendering the Helm release",
    )
    args = parser.parse_args()
    convert(args.manifest, args.output, args.namespace)


if __name__ == "__main__":
    main()
