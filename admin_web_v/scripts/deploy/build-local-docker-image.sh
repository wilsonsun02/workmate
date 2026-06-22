#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DOCKERFILE_PATH="${ROOT_DIR}/Dockerfile"

if [[ ! -f "${DOCKERFILE_PATH}" ]]; then
  echo "No Dockerfile found in ${ROOT_DIR}."
  echo "This workspace appears to be trimmed; docker image build is unavailable."
  exit 1
fi

docker build -f "${DOCKERFILE_PATH}" "${ROOT_DIR}"
