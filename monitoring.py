from dataclasses import dataclass
from typing import List, Optional

from kubernetes import client
from kubernetes.client import ApiException

from k8s_client import KubernetesManager


@dataclass
class NodeMetrics:
    name: str
    cpu_millicores: int
    memory_mebibytes: int
    pod_count: int
    kubelet_health: str
    karpenter_health: str


@dataclass
class PodMetrics:
    name: str
    namespace: str
    cpu_millicores: int
    memory_mebibytes: int


def _parse_quantity(value: str) -> int:
    if value.endswith("n"):
        return int(int(value[:-1]) / 1_000_000)
    if value.endswith("m"):
        return int(value[:-1])
    if value.endswith("Ki"):
        return int(int(value[:-2]) / 1024)
    if value.endswith("Mi"):
        return int(value[:-2])
    return int(value)


def fetch_node_metrics(k8s: KubernetesManager) -> List[NodeMetrics]:
    metrics: List[NodeMetrics] = []
    if getattr(k8s, "dummy_mode", False) or not getattr(k8s, "api_client", None):
        return metrics
    try:
        metrics_api = client.CustomObjectsApi(k8s.api_client)
        metric_response = metrics_api.list_cluster_custom_object(
            group="metrics.k8s.io", version="v1beta1", plural="nodes"
        )
        for item in metric_response.get("items", []):
            usage = item["usage"]
            name = item["metadata"]["name"]
            metrics.append(
                NodeMetrics(
                    name=name,
                    cpu_millicores=_parse_quantity(usage.get("cpu", "0")),
                    memory_mebibytes=_parse_quantity(usage.get("memory", "0")),
                    pod_count=len(k8s.list_pods(None, field_selector=f"spec.nodeName={name}")),
                    kubelet_health=_get_condition(k8s, name, "Ready"),
                    karpenter_health=_get_condition(k8s, name, "KarpenterInitialized"),
                )
            )
    except ApiException:
        pass
    return metrics


def fetch_pod_metrics(k8s: KubernetesManager, namespace: Optional[str]) -> List[PodMetrics]:
    results: List[PodMetrics] = []
    if getattr(k8s, "dummy_mode", False) or not getattr(k8s, "api_client", None):
        return results
    try:
        metrics_api = client.CustomObjectsApi(k8s.api_client)
        if namespace:
            response = metrics_api.list_namespaced_custom_object(
                group="metrics.k8s.io", version="v1beta1", plural="pods", namespace=namespace
            )
        else:
            response = metrics_api.list_cluster_custom_object(
                group="metrics.k8s.io", version="v1beta1", plural="pods"
            )
        for item in response.get("items", []):
            containers = item.get("containers", [])
            cpu = sum(_parse_quantity(c["usage"].get("cpu", "0")) for c in containers)
            mem = sum(_parse_quantity(c["usage"].get("memory", "0")) for c in containers)
            results.append(
                PodMetrics(
                    name=item["metadata"]["name"],
                    namespace=item["metadata"]["namespace"],
                    cpu_millicores=cpu,
                    memory_mebibytes=mem,
                )
            )
    except ApiException:
        pass
    return results


def _get_condition(k8s: KubernetesManager, node_name: str, condition_type: str) -> str:
    try:
        node = k8s.get_node(node_name)
        for condition in node.status.conditions or []:
            if condition.type == condition_type:
                return condition.status
    except ApiException:
        return "Unknown"
    return "Unknown"
