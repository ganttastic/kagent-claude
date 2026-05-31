#!/usr/bin/env bash
# Build and push the kagent-claude container image
set -euo pipefail

IMAGE="ghcr.io/ganttastic/kagent-claude"
TAG="${1:-latest}"

echo "Building ${IMAGE}:${TAG}..."
docker build -t "${IMAGE}:${TAG}" -f deploy/Dockerfile .

echo "Pushing ${IMAGE}:${TAG}..."
docker push "${IMAGE}:${TAG}"

echo "Done. Deploy with:"
echo "  kubectl apply -f deploy/k8s/deployment.yaml"
