# Contributing to AgenticOS

Thanks for considering a contribution.

## One-time setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ./services/shared
for s in api_gateway agent_runtime llm_gateway tool_registry knowledge_svc memory_svc worker; do
  pip install -e ./services/$s
done
pip install -r requirements-dev.txt pre-commit

pre-commit install                    # set up the git hooks
cd web-ui && npm install --no-audit --no-fund && cd -
```

## Workflow

1. Branch off `main` (`git switch -c feat/your-thing`).
2. Make changes; ensure tests cover them.
3. Run the same checks CI runs:

   ```bash
   ruff check services/ scripts/ tests/
   ruff format --check services/ scripts/ tests/
   pytest                                # unit + integration + evals
   helm lint deploy/helm/agenticos
   helm template agenticos deploy/helm/agenticos > /dev/null
   docker compose -f docker-compose.yml config -q
   ```
4. Commit using [Conventional Commits](https://www.conventionalcommits.org/)
   (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `perf:`, `test:`,
   `ci:`, `build:`). The `pre-commit` hook enforces this.
5. Push and open a PR. CI runs ruff/format/pytest/integration/evals,
   bandit, pip-audit, Semgrep, OpenAPI diff, web build, SDK typecheck,
   compose validate, and helm validate.

## Adding a new service or migration

* Service: copy one of the small existing services (`memory_svc` is the
  smallest) and edit `pyproject.toml`, `src/<pkg>/main.py`, and add a
  `tests/conftest.py`. Mount it in `services/Dockerfile`'s build args
  and `docker-compose.yml`.
* Migration: `make makemigration M="describe change"` from inside the
  compose stack, or write `migrations/versions/0NNN_*.py` by hand.
  Always validate with `alembic upgrade head --sql` before committing.

## License

All contributions are accepted under Apache-2.0 (same as the project).
