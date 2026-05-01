# Air-gapped install

Two scripts:

| Script        | Run on                  | Output                                       |
|---------------|-------------------------|----------------------------------------------|
| `bundle.sh`   | A connected build host  | `agenticos-airgap-<version>.tar.zst` archive |
| `install.sh`  | The air-gapped target   | Loaded images + a Helm release               |

## Quickstart

On a host with internet access:

```bash
./deploy/airgap/bundle.sh -v 0.1.0 -o /tmp
# → /tmp/agenticos-airgap-0.1.0.tar.zst (~3-5 GB depending on which
#   models you choose to bundle)
```

Copy the tarball onto the air-gapped network. Then on the target:

```bash
./deploy/airgap/install.sh /tmp/agenticos-airgap-0.1.0.tar.zst \
    --registry registry.internal.example.com:5000 \
    --namespace agenticos \
    --values ./values.yaml
```

`install.sh` runs `docker load`, retags every image into your internal
registry, pushes them, then `helm install`s the bundled chart pointing
at `--values`. The chart is the same one shipped under
`deploy/helm/agenticos`, just packaged.

## What's in the bundle

```
agenticos-airgap-<version>/
├── manifest.json                 # versions, sha256s, image list
├── images/
│   └── agenticos-images.tar      # multi-image tarball (all 8 services)
├── chart/
│   └── agenticos-<version>.tgz   # the packaged Helm chart
└── opa-policies/                 # the Rego bundles you ship by default
```

## Models

`bundle.sh -m qwen2.5:7b-instruct` pulls the named Ollama model into the
bundle alongside the images. Skip with `-m none` if you intend to host
inference outside the cluster. The default is `none`.

## Verifying the bundle

Each tarball has a sibling `*.sha256` you can validate against the
manifest before installing:

```bash
sha256sum -c agenticos-airgap-0.1.0.tar.zst.sha256
```

`install.sh` re-checks every per-image digest against the manifest after
the load step.
