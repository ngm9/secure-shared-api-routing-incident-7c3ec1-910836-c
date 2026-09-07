#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="utkrusht-api-edge"
LOCAL_BIN="${ROOT_DIR}/.local/bin"
K3D_BIN="${LOCAL_BIN}/k3d"
TOKEN_FILE="${ROOT_DIR}/cluster/dashboard-token.txt"

mkdir -p "${LOCAL_BIN}"
export PATH="${LOCAL_BIN}:${PATH}"

if ! command -v k3d >/dev/null 2>&1; then
  if [ ! -x "${K3D_BIN}" ]; then
    echo "Installing k3d into ${LOCAL_BIN}"
    curl -fsSL https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | TAG=v5.6.3 K3D_INSTALL_DIR="${LOCAL_BIN}" bash
  fi
fi

if command -v k3d >/dev/null 2>&1; then
  K3D_CMD="$(command -v k3d)"
else
  K3D_CMD="${K3D_BIN}"
fi

if ! "${K3D_CMD}" cluster list -o json | grep -q "\"name\":\"${CLUSTER_NAME}\""; then
  echo "Creating k3d cluster ${CLUSTER_NAME}"
  "${K3D_CMD}" cluster create "${CLUSTER_NAME}" \
    --servers 1 \
    --agents 0 \
    --wait \
    --timeout 120s \
    --k3s-arg "--disable=traefik@server:0"
else
  echo "Using existing k3d cluster ${CLUSTER_NAME}"
fi

"${K3D_CMD}" kubeconfig merge "${CLUSTER_NAME}" --kubeconfig-switch-context >/dev/null

for i in $(seq 1 60); do
  if kubectl get nodes >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

kubectl wait --for=condition=Ready node --all --timeout=180s
kubectl -n kube-system wait --for=condition=Ready pods --all --timeout=180s || true

echo "Building local application images"
docker build -t api1-local:latest "${ROOT_DIR}/api1" >/dev/null
docker build -t api2-local:latest "${ROOT_DIR}/api2" >/dev/null
"${K3D_CMD}" image import api1-local:latest api2-local:latest -c "${CLUSTER_NAME}" >/dev/null

echo "Installing ingress-nginx"
# The upstream "kind" provider manifest schedules the controller only onto
# nodes labeled ingress-ready=true -- kind sets this itself, k3d does not,
# so it must be applied explicitly or the controller pod stays Pending forever.
kubectl label node "k3d-${CLUSTER_NAME}-server-0" ingress-ready=true --overwrite >/dev/null
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.1/deploy/static/provider/kind/deploy.yaml >/dev/null
kubectl -n ingress-nginx wait --for=condition=Ready pod -l app.kubernetes.io/component=controller --timeout=180s

echo "Installing Kubernetes Dashboard"
kubectl apply -f https://raw.githubusercontent.com/kubernetes/dashboard/v2.7.0/aio/deploy/recommended.yaml >/dev/null
kubectl -n kubernetes-dashboard wait --for=condition=Ready pod -l k8s-app=kubernetes-dashboard --timeout=180s

kubectl apply -f - >/dev/null <<'YAML'
apiVersion: v1
kind: ServiceAccount
metadata:
  name: dashboard-admin
  namespace: kubernetes-dashboard
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: dashboard-admin
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
  - kind: ServiceAccount
    name: dashboard-admin
    namespace: kubernetes-dashboard
YAML

if [ ! -s "${TOKEN_FILE}" ]; then
  kubectl -n kubernetes-dashboard create token dashboard-admin > "${TOKEN_FILE}"
fi
chmod 0600 "${TOKEN_FILE}" || true

echo "Applying starter manifests"
kubectl apply -f "${ROOT_DIR}/manifests/namespaces.yaml"
find "${ROOT_DIR}/manifests" -mindepth 2 -type f \( -name '*.yaml' -o -name '*.yml' \) | sort | while read -r manifest; do
  kubectl apply -f "${manifest}"
done
kubectl apply -f "${ROOT_DIR}/manifests/ingress.yaml"

echo ""
echo "Starting cluster state:"
kubectl get pods -A

echo ""
echo "Kubernetes Dashboard access:"
echo "  kubectl -n kubernetes-dashboard port-forward svc/kubernetes-dashboard 9443:443"
echo "  Open the sandbox browser for forwarded port 9443."
echo "  Login token is written to: ${TOKEN_FILE}"
