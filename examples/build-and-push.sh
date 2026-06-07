#!/usr/bin/env bash
# Build and push a kagent-claude agent container image.
#
# Usage:
#   ./examples/build-and-push.sh ghcr.io/your-org/my-agent
#   ./examples/build-and-push.sh ghcr.io/your-org/my-agent v1.0.0
set -euo pipefail

IMAGE="${1:?Usage: $0 <image-name> [tag]}"
TAG="${2:-latest}"

echo "Building ${IMAGE}:${TAG}..."
docker build -t "${IMAGE}:${TAG}" -f examples/Dockerfile examples/

echo "Pushing ${IMAGE}:${TAG}..."
docker push "${IMAGE}:${TAG}"

echo ""
echo "Done. Deploy with:"
echo "  kubectl apply -f examples/agent.yaml"
echo ""
echo "Make sure to update the image in agent.yaml to: ${IMAGE}:${TAG}"
