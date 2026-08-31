# CodeAtlas deployment

This guide covers the credential-free deployment configuration included in the repository. It does not provision an account, domain, certificate, or secret store.

## Production topology

Use three independently managed components:

1. A Next.js container behind a CDN or reverse proxy for the browser application.
2. A FastAPI container behind the same reverse proxy (or on a dedicated API hostname).
3. A managed PostgreSQL instance with the `pgvector` extension enabled, reachable only from the API service.

Keep PostgreSQL off the public internet. Expose only the frontend and the API through HTTPS. Put a reverse proxy or platform ingress in front of the containers for TLS termination, request limits, and access logs. The provided `compose.yaml` is suitable for a single-host deployment and includes a pgvector database volume; for a managed database deployment, deploy the frontend and backend images separately and set `DATABASE_URL` in the backend service.

## Environment variables

Use the examples as variable names and documentation only:

- `backend/.env.example` documents backend settings, including database pooling, CORS, GitHub, and OpenAI configuration.
- `frontend/.env.example` documents the sole browser-visible setting: `NEXT_PUBLIC_API_URL`.
- `.env.example` documents values consumed by `compose.yaml`.

Never commit `.env`, `backend/.env`, `frontend/.env.local`, API keys, database passwords, or provider credentials. They are ignored by Git and Docker build contexts. Store production values in the hosting platform’s secret manager or in an access-restricted environment file on the deployment host.

`NEXT_PUBLIC_API_URL` is intentionally public and is embedded into the frontend JavaScript at image build time. Set it to the browser-reachable HTTPS API URL before building, for example `https://api.codeatlas.example`. Do not use the Docker service hostname (`backend`) for this value because browsers cannot resolve it.

Set `CORS_ALLOW_ORIGINS` on the backend to the exact comma-separated frontend origins, for example:

```text
CORS_ALLOW_ORIGINS=https://codeatlas.example,https://www.codeatlas.example
CORS_ALLOW_CREDENTIALS=true
```

Do not use `*` when credentials are enabled. The API rejects that unsafe configuration at startup.

## Manual single-host deployment with Docker Compose

1. Install Docker Engine and the Docker Compose plugin on the deployment host.
2. Clone the project, then copy `.env.example` to `.env` without committing it.
3. Set a strong `POSTGRES_PASSWORD`, `OPENAI_API_KEY`, and—if needed for GitHub rate limits—`GITHUB_TOKEN` in `.env` or inject them through your host’s secret manager. If the password contains URL-reserved characters, URL-encode it because Compose places it in `DATABASE_URL`.
4. Set `NEXT_PUBLIC_API_URL` to your public API URL and set `CORS_ALLOW_ORIGINS` to the exact public frontend origin. Configure the reverse proxy so that the API URL routes to port 8000 and the frontend URL routes to port 3000.
5. Build and start the stack:

```bash
docker compose --env-file .env up --build -d
```

6. Verify local container health from the host:

```bash
docker compose ps
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/readyz
curl -I http://127.0.0.1:3000/
```

`/health` is a liveness probe. `/readyz` also verifies the database and should return HTTP 200 only when the API can serve database-backed requests.

7. Verify through the public frontend: import a public repository, process embeddings, ask a question, run a review, and generate tests. Confirm browser requests go to the configured public API host and are accepted by CORS.

## Manual managed-service deployment

1. Provision PostgreSQL with pgvector enabled. Use a database role permitted to use the existing extension; the API runs `CREATE EXTENSION IF NOT EXISTS vector` during startup so the embedding schema cannot start without pgvector.
2. Build and deploy `backend/Dockerfile`. Set `DATABASE_URL`, `OPENAI_API_KEY`, optional `GITHUB_TOKEN`, explicit `CORS_ALLOW_ORIGINS`, and database pool settings in the service’s secret/environment configuration. Point the platform readiness check at `/readyz` and liveness check at `/health`.
3. Build and deploy `frontend/Dockerfile` with the build argument `NEXT_PUBLIC_API_URL=https://your-api-host`. Do not add OpenAI, GitHub, or database credentials to the frontend.
4. Place both services behind HTTPS, restrict database network access to the API, and configure any platform health probes as above.

For more than one API instance, size `DATABASE_POOL_SIZE` and `DATABASE_MAX_OVERFLOW` so the total possible connections across all instances stays below the database provider’s connection limit.

## CI

GitHub Actions workflow `.github/workflows/ci.yml` runs backend tests against a temporary pgvector PostgreSQL service and runs frontend tests, ESLint, TypeScript, and the production build. It uses no repository secrets and does not deploy.
