#!/usr/bin/env bash
# Bundle every container image and the Helm chart into a single
# air-gappable tarball. Run on a host with internet + docker + helm.
#
# Usage:
#   ./bundle.sh -v 0.1.0 -o /tmp
#   ./bundle.sh -v 0.1.0 -o /tmp -m qwen2.5:1.5b-instruct
#
# Flags:
#   -v VERSION   release version (default: read from Chart.yaml)
#   -o OUTDIR    output directory (default: ./dist)
#   -r REGISTRY  source registry (default: ghcr.io/msorokolit/agenticos)
#   -m MODEL     Ollama model to include; "none" to skip (default: none)
#   -h           print this help

set -euo pipefail

REGISTRY="${REGISTRY:-ghcr.io/msorokolit/agenticos}"
VERSION=""
OUTDIR="./dist"
MODEL="${MODEL:-none}"

usage() {
    sed -n '2,15p' "$0"
    exit 0
}

while getopts "v:o:r:m:h" opt; do
    case "$opt" in
        v) VERSION="$OPTARG" ;;
        o) OUTDIR="$OPTARG" ;;
        r) REGISTRY="$OPTARG" ;;
        m) MODEL="$OPTARG" ;;
        h) usage ;;
        *) echo "unknown flag" >&2; exit 2 ;;
    esac
done

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CHART_DIR="$ROOT/deploy/helm/agenticos"
POLICIES_DIR="$ROOT/policies"

if [ -z "$VERSION" ]; then
    VERSION="$(awk '/^version:/{print $2}' "$CHART_DIR/Chart.yaml")"
fi
if [ -z "$VERSION" ]; then
    echo "ERROR: --version not provided and could not be read from Chart.yaml" >&2
    exit 2
fi

mkdir -p "$OUTDIR"
WORK="$(mktemp -d)"
STAGE="$WORK/agenticos-airgap-$VERSION"
mkdir -p "$STAGE/images" "$STAGE/chart" "$STAGE/opa-policies"

# Required CLIs.
for tool in docker helm sha256sum tar; do
    command -v "$tool" >/dev/null || { echo "ERROR: $tool not on PATH" >&2; exit 2; }
done
# zstd is preferred but optional; fall back to gzip.
COMPRESSOR=""
EXT="tar.gz"
if command -v zstd >/dev/null; then
    COMPRESSOR="zstd"
    EXT="tar.zst"
fi

SERVICES=(
    api-gateway
    agent-runtime
    llm-gateway
    tool-registry
    knowledge-svc
    memory-svc
    worker
    web-ui
)

echo "==> pulling service images @ ${VERSION}"
IMAGE_REFS=()
for svc in "${SERVICES[@]}"; do
    ref="${REGISTRY}/${svc}:${VERSION}"
    echo "    docker pull $ref"
    docker pull "$ref"
    IMAGE_REFS+=("$ref")
done

# Optional model.
MODEL_TAR=""
if [ "$MODEL" != "none" ] && [ -n "$MODEL" ]; then
    echo "==> pulling Ollama model: $MODEL"
    OLLAMA_VOL="agenticos-airgap-ollama-$VERSION"
    docker volume create "$OLLAMA_VOL" >/dev/null
    docker run --rm -d --name "agenticos-ollama-bundle" \
        -v "${OLLAMA_VOL}:/root/.ollama" \
        ollama/ollama:latest >/dev/null
    # Wait for ollama
    for i in $(seq 1 30); do
        if docker exec agenticos-ollama-bundle ollama list >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    docker exec agenticos-ollama-bundle ollama pull "$MODEL"
    docker stop agenticos-ollama-bundle >/dev/null
    MODEL_TAR="$STAGE/models/${MODEL//[:\/]/_}.tar"
    mkdir -p "$STAGE/models"
    docker run --rm -v "${OLLAMA_VOL}:/data:ro" \
        -v "$STAGE/models:/out" alpine:3 \
        sh -c "cd /data && tar cf /out/$(basename "$MODEL_TAR") ."
    docker volume rm "$OLLAMA_VOL" >/dev/null
fi

echo "==> saving images"
docker save -o "$STAGE/images/agenticos-images.tar" "${IMAGE_REFS[@]}"

echo "==> packaging Helm chart"
helm package "$CHART_DIR" --version "$VERSION" --app-version "$VERSION" \
    --destination "$STAGE/chart"

echo "==> bundling default OPA policies"
cp -R "$POLICIES_DIR/." "$STAGE/opa-policies/"

echo "==> writing manifest"
python3 - <<PY > "$STAGE/manifest.json"
import json, hashlib, os, sys
stage = os.environ["STAGE"]
out = {
    "version": os.environ["VERSION"],
    "registry": os.environ["REGISTRY"],
    "images": [r for r in os.environ["IMAGE_REFS"].split("\n") if r],
    "files": {},
}
for root, _dirs, files in os.walk(stage):
    for f in sorted(files):
        if f == "manifest.json":
            continue
        p = os.path.join(root, f)
        rel = os.path.relpath(p, stage)
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        out["files"][rel] = {"sha256": h.hexdigest(), "bytes": os.path.getsize(p)}
print(json.dumps(out, indent=2, sort_keys=True))
PY
export STAGE VERSION REGISTRY IMAGE_REFS_BLOB
# Make it idempotent for subsequent runs.

echo "==> compressing bundle"
ARCHIVE="$OUTDIR/agenticos-airgap-${VERSION}.${EXT}"
if [ "$COMPRESSOR" = "zstd" ]; then
    tar -C "$WORK" -cf - "agenticos-airgap-$VERSION" \
        | zstd -19 -o "$ARCHIVE"
else
    tar -C "$WORK" -czf "$ARCHIVE" "agenticos-airgap-$VERSION"
fi

sha256sum "$ARCHIVE" > "${ARCHIVE}.sha256"
echo "==> wrote $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
echo "    sha256: $(cut -d' ' -f1 < "${ARCHIVE}.sha256")"

# Cleanup stage dir; keep the working tree small.
rm -rf "$WORK"
