"""Streamlit UI for the Kubernetes portal."""

import json
import os
import subprocess
from datetime import datetime
from typing import List, Optional, Tuple

import streamlit as st
from dotenv import load_dotenv

from ai_support import AISupport
from k8s_client import KubernetesManager, apply_yaml_manifest, restart_deployment
from monitoring import NodeMetrics, fetch_node_metrics, fetch_pod_metrics

load_dotenv()

st.set_page_config(page_title="Kubernetes Portal", layout="wide")


@st.cache_resource(show_spinner=False)
def get_k8s_manager() -> KubernetesManager:
    return KubernetesManager()


def execute_cli(command: str, kubeconfig: Optional[str], context: Optional[str]) -> Tuple[str, str, int]:
    """Run a kubectl/helm/aws command with the selected kubeconfig/context."""
    env = os.environ.copy()
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    if context:
        env.setdefault("KUBECTL_CONTEXT", context)
    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )
        return completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out", 124


def render_overview(k8s: KubernetesManager, namespace: Optional[str]) -> None:
    pods = k8s.list_pods(namespace)
    deployments = k8s.list_deployments(namespace)
    services = k8s.list_services(namespace)
    statefulsets = k8s.list_statefulsets(namespace)
    jobs = k8s.list_jobs(namespace)

    with st.container():
        st.markdown(
            """<style>
            .metric-card {background:#0e1117;border:1px solid #262730;padding:12px;border-radius:8px}
            </style>""",
            unsafe_allow_html=True,
        )
        cols = st.columns(6)
        cols[0].metric("Pods", len(pods))
        cols[1].metric("Deployments", len(deployments))
        cols[2].metric("Services", len(services))
        cols[3].metric("StatefulSets", len(statefulsets))
        cols[4].metric("Jobs", len(jobs))
        cols[5].metric("Namespaces", len(k8s.list_namespaces()))

    st.markdown("### Events")
    events = k8s.list_events(namespace)
    if not events:
        st.info("No events available for the selected scope.")
    else:
        st.dataframe(
            [
                {
                    "type": e.type,
                    "reason": e.reason,
                    "message": e.message,
                    "namespace": e.metadata.namespace,
                    "involvedObject": f"{e.involved_object.kind}/{e.involved_object.name}",
                    "age": e.last_timestamp,
                }
                for e in events
            ],
            use_container_width=True,
        )



def render_pods(k8s: KubernetesManager, namespace: Optional[str]) -> None:
    st.subheader("Pods")
    pods = k8s.list_pods(namespace)
    data = []
    for pod in pods:
        data.append(
            {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "node": pod.spec.node_name,
                "status": pod.status.phase,
                "restarts": sum((c.restart_count or 0) for c in pod.status.container_statuses or []),
                "age": pod.metadata.creation_timestamp,
            }
        )
    st.dataframe(data, use_container_width=True)

    st.subheader("Logs")
    selected_pod = st.selectbox("Select Pod", [p.metadata.name for p in pods]) if pods else None
    if selected_pod:
        container = st.text_input("Container (optional)", "") or None
        tail_lines = st.slider("Tail lines", 10, 1000, 200)
        logs = k8s.get_logs(selected_pod, namespace or "default", container, tail_lines)
        st.code(logs or "No logs", language="bash")



def render_workloads(k8s: KubernetesManager, namespace: Optional[str]) -> None:
    st.subheader("Deployments")
    deployments = k8s.list_deployments(namespace)
    st.dataframe(
        [
            {
                "name": d.metadata.name,
                "namespace": d.metadata.namespace,
                "ready": f"{d.status.ready_replicas or 0}/{d.status.replicas or 0}",
                "updated": d.status.updated_replicas,
                "available": d.status.available_replicas,
            }
            for d in deployments
        ],
        use_container_width=True,
    )

    st.subheader("StatefulSets")
    sts = k8s.list_statefulsets(namespace)
    st.dataframe(
        [
            {
                "name": s.metadata.name,
                "namespace": s.metadata.namespace,
                "ready": f"{s.status.ready_replicas or 0}/{s.status.replicas or 0}",
            }
            for s in sts
        ],
        use_container_width=True,
    )

    st.markdown("### Rollout restart")
    deploy_to_restart = st.selectbox("Deployment", [d.metadata.name for d in deployments]) if deployments else None
    if deploy_to_restart and st.button("Restart selected deployment"):
        st.success(
            restart_deployment(
                deploy_to_restart,
                namespace or "default",
                context_name=k8s.active_context.get("name"),
                kubeconfig=k8s.kubeconfig_path,
            )
        )



def render_monitoring(k8s: KubernetesManager, namespace: Optional[str]) -> None:
    st.subheader("Nodes")
    node_metrics: List[NodeMetrics] = fetch_node_metrics(k8s)
    node_table = []
    for metric in node_metrics:
        node_table.append(
            {
                "node": metric.name,
                "cpu(m)": metric.cpu_millicores,
                "memory(Mi)": metric.memory_mebibytes,
                "pods": metric.pod_count,
                "kubelet": metric.kubelet_health,
                "provisioner": metric.karpenter_health,
            }
        )
    st.dataframe(node_table, use_container_width=True)

    selected_node = st.selectbox("Inspect Node", [m.name for m in node_metrics]) if node_metrics else None
    if selected_node:
        node_detail = k8s.get_node(selected_node)
        pods_on_node = k8s.list_pods(namespace, field_selector=f"spec.nodeName={selected_node}")
        st.markdown(f"### {selected_node}")
        metadata = getattr(node_detail, "metadata", None)
        status = getattr(node_detail, "status", None)
        st.json(
            {
                "labels": getattr(metadata, "labels", {}) if node_detail else {},
                "conditions": [
                    {"type": c.type, "status": c.status, "reason": c.reason}
                    for c in (getattr(status, "conditions", []) if status else [])
                ],
            }
        )
        st.markdown("#### Pods on node")
        st.dataframe(
            [
                {
                    "pod": p.metadata.name,
                    "namespace": p.metadata.namespace,
                    "status": p.status.phase,
                }
                for p in pods_on_node
            ],
            use_container_width=True,
        )

    st.subheader("Pod Metrics")
    pod_metrics = fetch_pod_metrics(k8s, namespace)
    st.dataframe(
        [
            {
                "pod": m.name,
                "namespace": m.namespace,
                "cpu(m)": m.cpu_millicores,
                "memory(Mi)": m.memory_mebibytes,
            }
            for m in pod_metrics
        ],
        use_container_width=True,
    )



def render_yaml_editor(k8s: KubernetesManager, namespace: Optional[str]) -> None:
    st.subheader("YAML Editor")
    if k8s.dummy_mode:
        st.warning("Connect a kubeconfig to view or edit manifests.")
        return
    default_namespace = namespace or "default"
    resource_kind = st.selectbox("Resource Kind", ["Deployment", "StatefulSet", "Service", "ConfigMap", "Secret"])

    resource_loader = {
        "Deployment": k8s.list_deployments,
        "StatefulSet": k8s.list_statefulsets,
        "Service": k8s.list_services,
        "ConfigMap": k8s.list_configmaps,
        "Secret": k8s.list_secrets,
    }[resource_kind]

    resources = resource_loader(namespace)
    selected_name = st.selectbox("Resource", [r.metadata.name for r in resources]) if resources else None
    if selected_name:
        yaml_text = k8s.get_resource_yaml(resource_kind, selected_name, default_namespace)
        edited = st.text_area("Manifest", yaml_text, height=400)
        if st.button("Apply changes"):
            apply_yaml_manifest(
                edited,
                default_namespace,
                context_name=k8s.active_context.get("name"),
                kubeconfig=k8s.kubeconfig_path,
            )
            st.success("Manifest applied.")



def render_terminal(k8s: KubernetesManager) -> None:
    st.subheader("Integrated Terminal")
    st.caption("Commands are run with the selected context and kubeconfig, including kubectl, helm, or aws cli.")
    if k8s.dummy_mode:
        st.warning("Connect a kubeconfig to run terminal commands, port forwards, or Helm actions.")
        return
    default_cmd = "kubectl get pods"
    command = st.text_input("Command", default_cmd)
    if st.button("Run command"):
        stdout, stderr, code = execute_cli(command, k8s.kubeconfig_path, k8s.active_context.get("name"))
        st.code(stdout or "<no stdout>", language="bash")
        if stderr:
            st.error(stderr)
        st.caption(f"Exit code: {code}")

    st.markdown("### Port Forwarding")
    if "port_forward_proc" not in st.session_state:
        st.session_state["port_forward_proc"] = None
    pf_resource = st.text_input("Resource (pod/service name)")
    pf_namespace = st.text_input("Namespace", "default")
    local_port = st.number_input("Local port", value=8080, step=1)
    remote_port = st.number_input("Remote port", value=80, step=1)
    if st.button("Start port forward"):
        if not pf_resource:
            st.error("Provide a pod or service name to port forward.")
        else:
            cmd = f"kubectl port-forward {pf_resource} {local_port}:{remote_port} -n {pf_namespace}"
            env = os.environ.copy()
            if k8s.kubeconfig_path:
                env["KUBECONFIG"] = k8s.kubeconfig_path
            st.session_state["port_forward_proc"] = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
            )
            st.success(f"Started: {cmd}")
    if st.session_state.get("port_forward_proc"):
        if st.button("Stop port forward"):
            st.session_state["port_forward_proc"].terminate()
            st.session_state["port_forward_proc"] = None
            st.info("Port forward stopped.")



def render_helm(k8s: KubernetesManager) -> None:
    st.subheader("Helm Releases")
    if k8s.dummy_mode:
        st.info("Connect a kubeconfig to list or install Helm releases.")
        return
    stdout, stderr, code = execute_cli("helm list -A -o json", k8s.kubeconfig_path, k8s.active_context.get("name"))
    if code == 0:
        try:
            releases = json.loads(stdout)
            st.dataframe(releases, use_container_width=True)
        except json.JSONDecodeError:
            st.warning("Helm output could not be parsed. Showing raw output.")
            st.code(stdout)
    else:
        st.info("Helm not available or failed to run. Install helm in the runtime to enable this section.")
        if stderr:
            st.error(stderr)



def render_ai(k8s: KubernetesManager, namespace: Optional[str]) -> None:
    st.subheader("AI Support")
    ai_client = AISupport()
    if not getattr(ai_client, "client", None):
        st.info("Set OPENAI_API_KEY in a .env file to enable AI actions and log analysis.")
        return
    user_prompt = st.text_area(
        "Describe the action or investigation needed",
        "Example: Restart deployment 'nlpbenfits' in namespace 'uat'",
    )
    if st.button("Analyze and Execute"):
        result = ai_client.handle_request(user_prompt, k8s, namespace)
        st.write(result)

    st.markdown("### Log Diagnosis")
    target_pod = st.text_input("Pod to analyze", "")
    if st.button("Analyze logs") and target_pod:
        logs = k8s.get_logs(target_pod, namespace or "default")
        summary = ai_client.summarize_logs(logs)
        st.write(summary)



def render_header(k8s: KubernetesManager) -> Optional[str]:
    contexts = k8s.available_contexts
    context_names = [c["name"] for c in contexts]
    selected_context = st.sidebar.selectbox("Context", context_names)
    k8s.set_context(selected_context)

    namespaces = k8s.list_namespaces()
    namespace_names = [n.metadata.name for n in namespaces]
    namespace_filter = st.sidebar.selectbox("Namespace", ["All"] + namespace_names)
    st.sidebar.markdown("---")
    st.sidebar.caption(
        f"User: {k8s.active_user} | Context: {selected_context} | kubeconfig: {k8s.kubeconfig_path or 'default path'}"
    )
    return None if namespace_filter == "All" else namespace_filter


if __name__ == "__main__":
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "",
        [
            "Overview",
            "Pods",
            "Workloads",
            "Monitoring",
            "YAML Editor",
            "Terminal",
            "Helm",
            "AI",
        ],
        index=0,
    )
    k8s_manager = get_k8s_manager()
    if k8s_manager.connection_warning or k8s_manager.dummy_mode:
        st.sidebar.warning(
            k8s_manager.connection_warning
            or "No kubeconfig detected. Connect a kubeconfig file to enable live data."
        )
    namespace = render_header(k8s_manager)

    if page == "Overview":
        render_overview(k8s_manager, namespace)
    elif page == "Pods":
        render_pods(k8s_manager, namespace)
    elif page == "Workloads":
        render_workloads(k8s_manager, namespace)
    elif page == "Monitoring":
        render_monitoring(k8s_manager, namespace)
    elif page == "YAML Editor":
        render_yaml_editor(k8s_manager, namespace)
    elif page == "Terminal":
        render_terminal(k8s_manager)
    elif page == "Helm":
        render_helm(k8s_manager)
    elif page == "AI":
        render_ai(k8s_manager, namespace)
