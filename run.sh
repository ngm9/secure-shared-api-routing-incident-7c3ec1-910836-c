#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Checking Docker daemon"
docker info >/dev/null

echo "Checking kubectl"
command -v kubectl >/dev/null

echo "Bootstrapping Kubernetes cluster and starter state"
bash "${ROOT_DIR}/cluster/bootstrap.sh"

echo "Waiting for node readiness"
for i in $(seq 1 60); do
  if kubectl get nodes --no-headers 2>/dev/null | awk '{print $2}' | grep -q '^Ready$'; then
    break
  fi
  sleep 2
done
kubectl wait --for=condition=Ready node --all --timeout=120s

echo "Waiting for Kubernetes Dashboard readiness"
kubectl -n kubernetes-dashboard wait --for=condition=Ready pod -l k8s-app=kubernetes-dashboard --timeout=120s

echo ""
echo "Starting pod state:"
kubectl get pods -A

echo ""
echo "Dashboard access:"
echo "  kubectl -n kubernetes-dashboard port-forward svc/kubernetes-dashboard 9443:443"
echo "  Open the sandbox browser for forwarded port 9443."
echo "  Login token file: ${ROOT_DIR}/cluster/dashboard-token.txt"

echo ""
echo "Cluster is ready for investigation. Workload health is not asserted by this script."
