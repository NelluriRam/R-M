from datetime import datetime
from typing import Any, Dict, List, Optional

import os

import yaml
from kubernetes import client, config
from kubernetes.client import ApiException


class KubernetesManager:
    """Thin wrapper around the Kubernetes python client with safe fallbacks."""

    def __init__(self) -> None:
        self.api_client = None
        self.core = None
        self.apps = None
        self.batch = None
        self.events = None
        self.connection_warning: Optional[str] = None
        self.kubeconfig_path = os.getenv("KUBECONFIG")
        try:
            contexts, active = config.list_kube_config_contexts()
        except Exception as exc:  # noqa: BLE001
            contexts, active = [], None
            self.connection_warning = str(exc)

        if not contexts:
            self.available_contexts = [{"name": "No kubeconfig found"}]
            self.active_context = {"name": "disconnected", "context": {"user": "n/a"}}
            self.dummy_mode = True
        else:
            self.available_contexts = contexts
            self.active_context = active or contexts[0]
            self.dummy_mode = False
            self.kubeconfig_path = self.kubeconfig_path or (self.active_context.get("context") or {}).get(
                "config_source"
            )
            self.kubeconfig_path = self.kubeconfig_path or os.path.expanduser("~/.kube/config")
            self.set_context(self.active_context.get("name"))

    @property
    def active_user(self) -> str:
        context = self.active_context.get("context") or {}
        return (context.get("user") or "unknown-user") if isinstance(context, dict) else "unknown-user"

    def set_context(self, context_name: str) -> None:
        if self.dummy_mode:
            self.active_context = {"name": context_name, "context": {"user": "disconnected"}}
            return

        self.api_client = config.new_client_from_config(context=context_name)
        self.core = client.CoreV1Api(self.api_client)
        self.apps = client.AppsV1Api(self.api_client)
        self.batch = client.BatchV1Api(self.api_client)
        self.events = client.EventsV1Api(self.api_client)
        self.connection_warning = None

    # -------- Namespace & context helpers --------
    def list_namespaces(self):
        return self._safe_call(lambda: self.core.list_namespace().items, default=[])

    # -------- Workload listings --------
    def list_pods(self, namespace: Optional[str], field_selector: Optional[str] = None):
        if self.dummy_mode:
            return []
        if namespace:
            return self._safe_call(
                lambda: self.core.list_namespaced_pod(namespace=namespace, field_selector=field_selector).items, default=[]
            )
        return self._safe_call(
            lambda: self.core.list_pod_for_all_namespaces(field_selector=field_selector).items, default=[]
        )

    def list_deployments(self, namespace: Optional[str]):
        if self.dummy_mode:
            return []
        if namespace:
            return self._safe_call(lambda: self.apps.list_namespaced_deployment(namespace).items, default=[])
        return self._safe_call(lambda: self.apps.list_deployment_for_all_namespaces().items, default=[])

    def list_statefulsets(self, namespace: Optional[str]):
        if self.dummy_mode:
            return []
        if namespace:
            return self._safe_call(lambda: self.apps.list_namespaced_stateful_set(namespace).items, default=[])
        return self._safe_call(lambda: self.apps.list_stateful_set_for_all_namespaces().items, default=[])

    def list_services(self, namespace: Optional[str]):
        if self.dummy_mode:
            return []
        if namespace:
            return self._safe_call(lambda: self.core.list_namespaced_service(namespace).items, default=[])
        return self._safe_call(lambda: self.core.list_service_for_all_namespaces().items, default=[])

    def list_jobs(self, namespace: Optional[str]):
        if self.dummy_mode:
            return []
        if namespace:
            return self._safe_call(lambda: self.batch.list_namespaced_job(namespace).items, default=[])
        return self._safe_call(lambda: self.batch.list_job_for_all_namespaces().items, default=[])

    def list_configmaps(self, namespace: Optional[str]):
        if self.dummy_mode:
            return []
        if namespace:
            return self._safe_call(lambda: self.core.list_namespaced_config_map(namespace).items, default=[])
        return self._safe_call(lambda: self.core.list_config_map_for_all_namespaces().items, default=[])

    def list_secrets(self, namespace: Optional[str]):
        if self.dummy_mode:
            return []
        if namespace:
            return self._safe_call(lambda: self.core.list_namespaced_secret(namespace).items, default=[])
        return self._safe_call(lambda: self.core.list_secret_for_all_namespaces().items, default=[])

    def list_events(self, namespace: Optional[str]):
        if self.dummy_mode:
            return []
        if namespace:
            return self._safe_call(lambda: self.events.list_namespaced_event(namespace).items, default=[])
        return self._safe_call(lambda: self.events.list_event_for_all_namespaces().items, default=[])

    def get_logs(
        self, pod_name: str, namespace: str, container: Optional[str] = None, tail_lines: int = 200
    ) -> str:
        if self.dummy_mode:
            return "No kubeconfig loaded; cannot fetch logs."
        try:
            return self.core.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=container,
                tail_lines=tail_lines,
            )
        except ApiException as exc:
            return f"Unable to fetch logs: {exc}"

    def get_node(self, node_name: str):
        if self.dummy_mode:
            return None
        return self._safe_call(lambda: self.core.read_node(node_name))

    # -------- YAML helpers --------
    def get_resource_yaml(self, kind: str, name: str, namespace: str) -> str:
        if self.dummy_mode:
            return "No kubeconfig loaded; unable to load manifest."
        loader = {
            "Deployment": lambda: self.apps.read_namespaced_deployment(name, namespace),
            "StatefulSet": lambda: self.apps.read_namespaced_stateful_set(name, namespace),
            "Service": lambda: self.core.read_namespaced_service(name, namespace),
            "ConfigMap": lambda: self.core.read_namespaced_config_map(name, namespace),
            "Secret": lambda: self.core.read_namespaced_secret(name, namespace),
        }[kind]
        obj = loader()
        return yaml.safe_dump(self._strip_status(obj.to_dict()))

    def _strip_status(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        manifest.pop("status", None)
        return manifest

    def _safe_call(self, func, default=None):
        try:
            return func()
        except ApiException as exc:
            self.connection_warning = str(exc)
            return default
        except Exception:  # noqa: BLE001
            return default


# -------- Mutating helpers outside the class --------
def apply_yaml_manifest(
    manifest: str, namespace: str, context_name: Optional[str] = None, kubeconfig: Optional[str] = None
) -> None:
    parsed = list(yaml.safe_load_all(manifest))
    for doc in parsed:
        if not doc:
            continue
        doc.setdefault("metadata", {}).setdefault("namespace", namespace)
        _apply_single(doc, context_name=context_name, kubeconfig=kubeconfig)


def _apply_single(doc: Dict[str, Any], context_name: Optional[str] = None, kubeconfig: Optional[str] = None) -> None:
    kind = doc.get("kind")
    metadata = doc.get("metadata", {})
    name = metadata.get("name")
    namespace = metadata.get("namespace")
    api = config.new_client_from_config(config_file=kubeconfig, context=context_name)

    if kind == "Deployment":
        api_instance = client.AppsV1Api(api)
        try:
            api_instance.read_namespaced_deployment(name, namespace)
            api_instance.patch_namespaced_deployment(name, namespace, doc)
        except ApiException:
            api_instance.create_namespaced_deployment(namespace, doc)
    elif kind == "StatefulSet":
        api_instance = client.AppsV1Api(api)
        try:
            api_instance.read_namespaced_stateful_set(name, namespace)
            api_instance.patch_namespaced_stateful_set(name, namespace, doc)
        except ApiException:
            api_instance.create_namespaced_stateful_set(namespace, doc)
    elif kind == "Service":
        api_instance = client.CoreV1Api(api)
        try:
            api_instance.read_namespaced_service(name, namespace)
            api_instance.patch_namespaced_service(name, namespace, doc)
        except ApiException:
            api_instance.create_namespaced_service(namespace, doc)
    elif kind == "ConfigMap":
        api_instance = client.CoreV1Api(api)
        try:
            api_instance.read_namespaced_config_map(name, namespace)
            api_instance.patch_namespaced_config_map(name, namespace, doc)
        except ApiException:
            api_instance.create_namespaced_config_map(namespace, doc)
    elif kind == "Secret":
        api_instance = client.CoreV1Api(api)
        try:
            api_instance.read_namespaced_secret(name, namespace)
            api_instance.patch_namespaced_secret(name, namespace, doc)
        except ApiException:
            api_instance.create_namespaced_secret(namespace, doc)
    else:
        raise ValueError(f"Unsupported kind {kind}")


def restart_deployment(
    name: str, namespace: str, context_name: Optional[str] = None, kubeconfig: Optional[str] = None
) -> str:
    api = config.new_client_from_config(config_file=kubeconfig, context=context_name)
    apps = client.AppsV1Api(api)
    try:
        deployment = apps.read_namespaced_deployment(name, namespace)
    except ApiException as exc:
        return f"Deployment fetch failed: {exc}"

    annotations = deployment.spec.template.metadata.annotations or {}
    annotations["kubectl.kubernetes.io/restartedAt"] = datetime.utcnow().isoformat() + "Z"
    deployment.spec.template.metadata.annotations = annotations

    try:
        apps.patch_namespaced_deployment(name, namespace, deployment)
        return f"Deployment {name} restarted"
    except ApiException as exc:
        return f"Deployment restart failed: {exc}"
