#!/usr/bin/env bash
# Install AgenticOS from an air-gapped bundle produced by ``bundle.sh``.
# Run on a target with docker + helm + (optionally) kubectl.
#
# Usage:
#   ./install.sh BUNDLE.tar.{zst,gz} \
#       --registry registry.internal.example.com:5000 \
#       --namespace agenticos \
#       --release agenticos \
#       --values ./prod-values.yaml
#
# What it does:
#   1. Verifies sha256 against BUNDLE.sha256.
#   2. Extracts the bundle to a temp dir.
#   3. ``docker load``s every image, retags to --registry, pushes.
#   4. ``helm install`` (or ``upgrade --install``) the bundled chart
#      pointing at the new image registry.
#
# Flags:
#   --registry REG      target image registry (required)
#   --namespace NS      kubernetes namespace (default: agenticos)
#   --release NAME      helm release name (default: agenticos)
#   --values FILE       additional helm values file (optional, repeatable)
#   --dry-run           print what would happen, don't install
#   --skip-push         re-tag locally but don't push (handy for kind)
#   -h, --help          this help

set -euo pipefail

BUNDLE=""
REGISTRY=""
NAMESPACE="agenticos"
RELEASE="agenticos"
VALUES=()
DRY_RUN=false
SKIP_PUSH=false

usage() { sed -n '2,30p' "$0"; exit 0; }

while [ $# -gt 0 ]; do
    case "$1" in
        --registry)  REGISTRY="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        --release)   RELEASE="$2"; shift 2 ;;
        --values)    VALUES+=("-f" "$2"); shift 2 ;;
        --dry-run)   DRY_RUN=true; shift ;;
        --skip-push) SKIP_PUSH=true; shift ;;
        -h|--help)   usage ;;
        -*)          echo "unknown flag $1" >&2; exit 2 ;;
        *)           BUNDLE="$1"; shift ;;
    esac
done

if [ -z "$BUNDLE" ] || [ -z "$REGISTRY" ]; then
    usage
fi
[ -f "$BUNDLE" ] || { echo "ERROR: bundle not found: $BUNDLE" >&2; exit 2; }

for tool in docker helm sha256sum tar; do
    command -v "$tool" >/dev/null || { echo "ERROR: $tool not on PATH" >&2; exit 2; }
done

if [ -f "${BUNDLE}.sha256" ]; then
    echo "==> verifying $BUNDLE against ${BUNDLE}.sha256"
    sha256sum -c "${BUNDLE}.sha256"
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

case "$BUNDLE" in
    *.tar.zst) command -v zstd >/dev/null || { echo "ERROR: zstd required" >&2; exit 2; }
               zstd -dc "$BUNDLE" | tar -C "$WORK" -xf - ;;
    *.tar.gz)  tar -C "$WORK" -xzf "$BUNDLE" ;;
    *)         echo "ERROR: unrecognised bundle extension: $BUNDLE" >&2; exit 2 ;;
esac

STAGE="$(find "$WORK" -maxdepth 1 -type d -name 'agenticos-airgap-*' | head -n1)"
[ -d "$STAGE" ] || { echo "ERROR: bundle layout looks wrong" >&2; exit 2; }

VERSION="$(jq -r .version "$STAGE/manifest.json" 2>/dev/null || awk -F\" '/"version":/{print $4; exit}' "$STAGE/manifest.json")"
SOURCE_REGISTRY="$(jq -r .registry "$STAGE/manifest.json" 2>/dev/null || awk -F\" '/"registry":/{print $4; exit}' "$STAGE/manifest.json")"
echo "==> bundle version: $VERSION"
echo "==> source registry: $SOURCE_REGISTRY"
echo "==> target registry: $REGISTRY"

# Re-verify per-file sha256s if jq is available.
if command -v jq >/dev/null; then
    echo "==> verifying per-file sha256s"
    while IFS= read -r line; do
        rel="$(echo "$line" | jq -r '.key')"
        want="$(echo "$line" | jq -r '.value.sha256')"
        got="$(sha256sum "$STAGE/$rel" | cut -d' ' -f1)"
        if [ "$want" != "$got" ]; then
            echo "FAIL  $rel: $got (expected $want)" >&2
            exit 2
        fi
    done < <(jq -c '.files | to_entries[]' "$STAGE/manifest.json")
fi

echo "==> docker load"
docker load -i "$STAGE/images/agenticos-images.tar"

# Re-tag every loaded image with the target registry.
RETAGGED=()
for src in $(jq -r '.images[]' "$STAGE/manifest.json"); do
    # source ref looks like ghcr.io/<owner>/agenticos/<svc>:<ver>
    repo="${src##*/}"               # <svc>:<ver>
    svc="${repo%%:*}"
    tag="${repo##*:}"
    dst="${REGISTRY}/${svc}:${tag}"
    echo "    retag $src -> $dst"
    docker tag "$src" "$dst"
    RETAGGED+=("$dst")
done

if [ "$SKIP_PUSH" = false ]; then
    for ref in "${RETAGGED[@]}"; do
        echo "    push $ref"
        if [ "$DRY_RUN" = false ]; then
            docker push "$ref"
        fi
    done
fi

CHART="$(ls "$STAGE/chart/"*.tgz | head -n1)"
[ -f "$CHART" ] || { echo "ERROR: no chart in bundle" >&2; exit 2; }
echo "==> chart: $CHART"

set -x
helm upgrade --install "$RELEASE" "$CHART" \
    --namespace "$NAMESPACE" --create-namespace \
    --set "global.image.registry=$REGISTRY" \
    --set "global.image.repository=" \
    --set "global.image.tag=$VERSION" \
    "${VALUES[@]}" \
    $( [ "$DRY_RUN" = true ] && echo --dry-run )
set +x

echo "==> done. Check pods with: kubectl -n $NAMESPACE get pods"
