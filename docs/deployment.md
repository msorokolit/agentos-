# Deployment

Phase 0 ships **Docker Compose** for local dev. Full Helm chart and
air-gapped bundler land in Phase 6.

## Prerequisites

- Docker 24+ and Docker Compose v2.
- ~16 GB RAM (more if you swap small models for larger ones).
- ~20 GB free disk for default models.
- (Optional) NVIDIA GPU + nvidia-container-toolkit for Ollama acceleration.

## First run

```bash
git clone https://github.com/msorokolit/agentos- agenticos
cd agenticos
cp .env.example .env

make dev          # build images, bring stack up, run migrations
make pull-models  # pulls default qwen2.5:7b-instruct + nomic-embed-text
make smoke        # hits /healthz on every service
```

Then open:

- Web UI: http://localhost:3000
- API: http://localhost:8080/healthz
- Keycloak admin: http://localhost:8090 (admin / admin)
- MinIO console: http://localhost:9001 (agenticos / agenticos-minio)
- Grafana: http://localhost:3001 (admin / admin)

## Updating

```bash
git pull
make down && make dev
```

## Resetting all data

```bash
make nuke         # deletes named volumes (postgres, redis, minio, ollama, grafana)
```

## GPU

Edit `docker-compose.yml`'s `ollama` service to add:

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
```

Then `make down && make dev`.

## Helm / Kubernetes

Coming in Phase 6 (`deploy/helm/agenticos/`). The compose file is a
faithful precursor: every service maps 1:1 to a Deployment; data services
to StatefulSets.
