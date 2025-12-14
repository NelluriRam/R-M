import os
import re
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

from k8s_client import KubernetesManager, restart_deployment


@dataclass
class Intent:
    action: str
    target: str
    namespace: str
    environment: Optional[str] = None


class AISupport:
    """Lightweight helper that routes natural language asks into safe actions."""

    def __init__(self) -> None:
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            self.client = None
            return
        self.client = OpenAI(api_key=api_key)

    def handle_request(self, prompt: str, k8s: KubernetesManager, namespace: Optional[str]) -> str:
        intent = self._parse_intent(prompt, namespace)
        if intent and intent.action == "restart":
            return restart_deployment(
                intent.target,
                intent.namespace,
                context_name=getattr(k8s, "active_context", {}).get("name") if k8s else None,
                kubeconfig=getattr(k8s, "kubeconfig_path", None) if k8s else None,
            )

        explanation = self._chat(
            "You are an SRE copilots for Kubernetes."
            f" User request: {prompt}."
            " Produce a concise execution plan with kubectl/helm commands,"
            " include RBAC considerations, and do not assume success."
        )
        return explanation

    def summarize_logs(self, logs: str) -> str:
        snippet = logs[:12000]
        return self._chat(
            "Analyze these Kubernetes pod logs, identify the most probable root cause,"
            " outline the blast radius (pods, services, nodes), and recommend concrete kubectl"
            " or manifest changes to remediate."
            f"\nLogs:\n{snippet}"
        )

    def _chat(self, prompt: str) -> str:
        if not self.client:
            return "OpenAI API key is not configured."

        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.15,
        )
        return response.choices[0].message.content

    def _parse_intent(self, prompt: str, default_namespace: Optional[str]):
        match = re.search(r"restart\s+(deployment|service|app)?\s*([\w-]+)", prompt, re.IGNORECASE)
        namespace_match = re.search(r"namespace\s*[:=]?\s*([\w-]+)", prompt, re.IGNORECASE)
        env_match = re.search(r"env\s*[:=]?\s*([\w-]+)", prompt, re.IGNORECASE)
        if match:
            target = match.group(2)
            namespace = namespace_match.group(1) if namespace_match else (default_namespace or "default")
            environment = env_match.group(1) if env_match else None
            return Intent(action="restart", target=target, namespace=namespace, environment=environment)
        return None
