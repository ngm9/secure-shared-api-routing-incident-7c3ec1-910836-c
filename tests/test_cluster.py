import json
import os
import re
import socket
import subprocess
import time

import pytest

PORT_FORWARDS = []
HOST = "api.utkrusht.local"


def run(cmd, check=True, timeout=30):
    result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode != 0:
        raise AssertionError(
            f"command failed: {' '.join(cmd)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def kubectl(args, check=True, timeout=30):
    return run(["kubectl"] + args, check=check, timeout=timeout)


def free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def cleanup_port_forwards():
    while PORT_FORWARDS:
        proc = PORT_FORWARDS.pop()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    subprocess.run(["pkill", "-f", "kubectl.*port-forward.*ingress-nginx-controller"], capture_output=True)


@pytest.fixture(autouse=True)
def clean_port_forwards():
    cleanup_port_forwards()
    yield
    cleanup_port_forwards()


def start_ingress_forward():
    port = free_port()
    proc = subprocess.Popen(
        [
            "kubectl",
            "-n",
            "ingress-nginx",
            "port-forward",
            "svc/ingress-nginx-controller",
            f"{port}:443",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    PORT_FORWARDS.append(proc)
    deadline = time.time() + 30
    while time.time() < deadline:
        if proc.poll() is not None:
            out, err = proc.communicate(timeout=2)
            raise AssertionError(f"ingress port-forward exited early\nstdout:\n{out}\nstderr:\n{err}")
        probe = subprocess.run(
            ["curl", "-k", "-sS", "-o", "/dev/null", "-w", "%{http_code}", f"https://127.0.0.1:{port}/health", "-H", f"Host: {HOST}"],
            text=True,
            capture_output=True,
            timeout=5,
        )
        if probe.returncode == 0:
            return port
        time.sleep(0.5)
    raise AssertionError("could not establish port-forward to ingress controller service")


def curl_ingress(path):
    port = start_ingress_forward()
    return run(
        [
            "curl",
            "-k",
            "-sS",
            "-o",
            "/tmp/ingress-body.txt",
            "-w",
            "%{http_code}",
            f"https://127.0.0.1:{port}{path}",
            "-H",
            f"Host: {HOST}",
        ],
        check=False,
        timeout=15,
    )


def parse_cpu(value):
    if value.endswith("m"):
        return int(value[:-1])
    return int(float(value) * 1000)


def parse_mem(value):
    units = {
        "Ki": 1024,
        "Mi": 1024 ** 2,
        "Gi": 1024 ** 3,
        "Ti": 1024 ** 4,
        "K": 1000,
        "M": 1000 ** 2,
        "G": 1000 ** 3,
    }
    for suffix, multiplier in units.items():
        if value.endswith(suffix):
            return int(float(value[: -len(suffix)]) * multiplier)
    return int(value)


def deployment_json(namespace, name):
    return json.loads(kubectl(["-n", namespace, "get", "deployment", name, "-o", "json"]).stdout)


def desired_request_totals():
    total_cpu = 0
    total_mem = 0
    for namespace, name in [("api1", "api1"), ("api2", "api2")]:
        dep = deployment_json(namespace, name)
        replicas = dep.get("spec", {}).get("replicas", 1)
        pod_cpu = 0
        pod_mem = 0
        for container in dep["spec"]["template"]["spec"].get("containers", []):
            requests = container.get("resources", {}).get("requests", {})
            pod_cpu += parse_cpu(requests.get("cpu", "0"))
            pod_mem += parse_mem(requests.get("memory", "0"))
        total_cpu += pod_cpu * replicas
        total_mem += pod_mem * replicas
    return total_cpu, total_mem


def node_allocatable():
    nodes = json.loads(kubectl(["get", "nodes", "-o", "json"]).stdout)["items"]
    assert len(nodes) == 1, "grader expects the provided single-node cluster"
    alloc = nodes[0]["status"]["allocatable"]
    return parse_cpu(alloc["cpu"]), parse_mem(alloc["memory"])


def test_tls_material_exists_and_is_referenced_by_shared_entrypoint():
    secret = kubectl(["-n", "edge", "get", "secret", "shared-api-tls", "-o", "json"], check=False)
    assert secret.returncode == 0, "secure entrypoint material is not present in the edge area"
    secret_json = json.loads(secret.stdout)
    assert secret_json.get("type") == "kubernetes.io/tls", "secure entrypoint material is not a Kubernetes TLS secret"

    ingress = json.loads(kubectl(["-n", "edge", "get", "ingress", "shared-api-ingress", "-o", "json"]).stdout)
    referenced = [item.get("secretName") for item in ingress.get("spec", {}).get("tls", [])]
    assert "shared-api-tls" in referenced, "shared entrypoint does not reference the expected secure material"


def test_first_api_rollout_is_available_and_clean():
    status = kubectl(["-n", "api1", "rollout", "status", "deployment/api1", "--timeout=90s"], check=False, timeout=100)
    assert status.returncode == 0, "first API rollout did not become available"
    pods = kubectl(["-n", "api1", "describe", "pods"]).stdout
    assert "CrashLoopBackOff" not in pods and "ImagePullBackOff" not in pods, "first API pods show container failure symptoms"


def test_second_api_rollout_reaches_all_expected_replicas():
    status = kubectl(["-n", "api2", "rollout", "status", "deployment/api2", "--timeout=120s"], check=False, timeout=130)
    assert status.returncode == 0, "second API did not reach all expected ready replicas"
    dep = json.loads(kubectl(["-n", "api2", "get", "deployment", "api2", "-o", "json"]).stdout)
    expected = dep["spec"].get("replicas", 1)
    ready = dep.get("status", {}).get("readyReplicas", 0)
    assert ready == expected, f"second API has {ready} ready replicas, expected {expected}"


def test_secure_shared_entrypoint_serves_first_api_path():
    response = curl_ingress("/api1/health")
    assert response.returncode == 0, f"request to first API path failed: {response.stderr}"
    assert response.stdout == "200", f"first API path returned HTTP {response.stdout}, expected 200"


def test_secure_shared_entrypoint_serves_second_api_path():
    response = curl_ingress("/api2/health")
    assert response.returncode == 0, f"request to second API path failed: {response.stderr}"
    assert response.stdout == "200", f"second API path returned HTTP {response.stdout}, expected 200"


def test_declared_workload_requests_fit_single_node_allocatable_capacity():
    planned_cpu, planned_mem = desired_request_totals()
    alloc_cpu, alloc_mem = node_allocatable()
    describe = kubectl(["describe", "node"], check=True).stdout
    assert "Allocated resources" in describe, "node description did not include allocated resource information"
    assert planned_cpu <= alloc_cpu, (
        f"declared CPU requests for the desired replicas are {planned_cpu}m, "
        f"but the single node allocates only {alloc_cpu}m"
    )
    assert planned_mem <= alloc_mem, (
        f"declared memory requests for the desired replicas are {planned_mem} bytes, "
        f"but the single node allocates only {alloc_mem} bytes"
    )
