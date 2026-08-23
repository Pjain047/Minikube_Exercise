# Minikube_Exercise
This repo will have python code with Infra that can be deployed on minikube local using CI (push image to dockerhub) and CD to deploy on minikube , the CI and CD we will use github
## Minikube Exercise

App runs with FastAPI. To build and run the Docker image for the `App` service:

```bash
cd App
docker build -t minikube-exercise-app:latest .
docker run -p 8000:8000 minikube-exercise-app:latest
```

Then open Swagger UI at: http://localhost:8000/docs

CI/CD
------

This repo includes a GitHub Actions workflow that builds and pushes the `App` Docker image to Docker Hub when changes land on `main` or when a pull request is merged into `main`.

Required repository secrets (set in GitHub Settings → Secrets):
- `DOCKERHUB_USERNAME` — your Docker Hub username
- `DOCKERHUB_TOKEN` — a Docker Hub access token or password

Image tags produced by the workflow:
- `<DOCKERHUB_USERNAME>/minikube-exercise-app:<version>` where `<version>` is `v{YYYYMMDDHHMMSS}-{shortCommit}` (UTC date/time + short commit SHA)
- `<DOCKERHUB_USERNAME>/minikube-exercise-app:latest`

Example: `jdoe/minikube-exercise-app:v20260822123045-ab12c3d`

Local deploy to Minikube (recommended)
------------------------------------

Deploy locally using the `Infrastructure/` manifests. Two local workflows are provided:

- PowerShell script (`deploy-ui/deploy-minikube.ps1`): prompts for an `owner/repo:tag` (or accepts `-Image`), generates manifests from `Infrastructure/deployment.yaml.template` (replacing `IMAGE_PLACEHOLDER`), applies them with `kubectl`, waits for the rollout, attempts to resolve the service URL via `minikube service`, and opens the Swagger UI (`/docs`) when available. This is the simplest local flow on Windows.

- Browser-driven flow (`deploy-ui/local_deploy.html`) — a small static page that posts `{ image, mode: 'local' }` to a local deploy server if you prefer a server-driven option. The deploy server (`deploy-ui/server.py`) is optional and can run where `kubectl`/`minikube` are available.

PowerShell quick start (recommended on Windows):

```powershell
# interactive
.\deploy-ui\deploy-minikube.ps1
# or provide image directly
.\deploy-ui\deploy-minikube.ps1 -Image 'myuser/minikube-exercise-app:v20260822-ab12c3d'
```

Browser UI quick start (optional server flow):

Run the deploy server on the machine that has `kubectl`/`minikube` access, then open the static UI in your browser.

```powershell
cd C:\MyProject_2026\Minikube_Exercise\deploy-ui

# create/activate venv (only once)
python -m venv .venv
.venv\Scripts\Activate

# ensure server deps installed
pip install fastapi uvicorn[standard] httpx pydantic

# run uvicorn and watch logs (bind to localhost)
uvicorn server:app --host 127.0.0.1 --port 9000 --reload

# then open the static UI (serve or open local_deploy.html)
```

Open `deploy-ui/local_deploy.html` in your browser, enter the Docker Hub image (for example `youruser/minikube-exercise-app:v20260822-ab12c3d`), and click `Trigger Deploy`. The server will perform a local-mode deploy: load/pull the image into Minikube, replace the placeholder, apply manifests, and wait for rollout. The UI will open the Swagger UI once the service is available.




3. In the Actions UI, open the `Manual deploy to Minikube` workflow and enter the Docker image tag to deploy (for example `youruser/minikube-exercise-app:v20260822123045-ab12c3d`).

4. The workflow will replace the `IMAGE_PLACEHOLDER` in `Infrastructure/deployment.yaml.template` and apply the manifests.

Accessing the app at `http://my-minikubeapp.com`:

- If using a LoadBalancer service in Minikube, run `minikube tunnel` on the Minikube host to allocate an external IP for the LoadBalancer.
- Find the external IP with `kubectl get svc minikube-app-service` and add a host entry mapping `my-minikubeapp.com` to that IP in your `/etc/hosts` (or Windows `C:\Windows\System32\drivers\etc\hosts`).
- Alternatively, enable the `ingress` addon in Minikube (`minikube addons enable ingress`) and ensure an ingress controller is running, then map `my-minikubeapp.com` to the Minikube IP in `/etc/hosts`.

Using the local Deploy UI (static)
--------------------------------

A small static UI is available at `deploy-ui/local_deploy.html`. It lets you enter a Docker Hub image (`owner/repo:tag`) and either:

- Post to a running local deploy server (`deploy-ui/server.py`) at `http://localhost:9000` (optional), or
- Use the PowerShell script (`deploy-ui/deploy-minikube.ps1`) directly without a server.

The static UI does not require any tokens when used in `local` mode and does not store any credentials.


---

**Project documentation (full)**

Overview
- This repository contains a small FastAPI application (`App/`) with a Dockerfile, Kubernetes manifests (`Infrastructure/`), CI to build and push Docker images, and local deployment tooling to deploy to a local Minikube cluster.
- A lightweight Deploy UI (`deploy-ui/`) plus an optional server (`deploy-ui/server.py`) are included as helpers. The preferred local workflow is to use `deploy-ui/deploy-minikube.ps1` or the static `deploy-ui/local_deploy.html` UI.

Main components
- `App/` — FastAPI app, SQLite-backed, with `Dockerfile` and `requirements.txt`.
- `.github/workflows/publish-dockerhub.yml` — CI workflow to build and push images to Docker Hub on pushes/merged PRs to `main`.
-- `.github/workflows/manual-deploy-minikube.yml` — (previous) manual deploy workflow removed; deployments are now handled locally via scripts or the optional deploy server.
-- `Infrastructure/` — Kubernetes manifests: `deployment.yaml.template`, `service.yaml`, `ingress.yaml`.
-- `deploy-ui/` — deploy helpers: `deploy-minikube.ps1` (PowerShell script), `local_deploy.html` (static browser UI), and `server.py` (optional FastAPI deploy server).
-- `scripts/` — previously contained helper scripts for self-hosted runner setup and hosts editing; these were removed to simplify local workflows.

High-level flow
1. Developer pushes to `main` → CI builds Docker image and pushes to Docker Hub. The image is tagged as `v{YYYYMMDDHHMMSS}-{shortSHA}` and `latest`.
2. Developer chooses an image tag via the local deploy script (`deploy-ui/deploy-minikube.ps1`) or the static UI (`deploy-ui/local_deploy.html`) and triggers a local deploy.
3. The chosen image is pulled or loaded into Minikube (if necessary), the `IMAGE_PLACEHOLDER` is replaced in `Infrastructure/deployment.yaml.template`, and manifests are applied with `kubectl`.
4. The deploy script or server waits for rollout and can report the service URL and health; the Swagger UI is opened automatically when available.

Step-by-step setup (quick)
- Prereqs: Docker, Minikube, kubectl, Python 3.10+, Git, and access to a Docker Hub account.
- 1) Build & test app locally:
	```bash
	cd App
	python -m venv .venv
	source .venv/bin/activate
	pip install -r requirements.txt
	uvicorn app:app --reload
	```

- 2) Build image locally (optional):
	```bash
	docker build -t youruser/minikube-exercise-app:localtest App/
	docker run -p 8000:8000 youruser/minikube-exercise-app:localtest
	```

3) (Optional) The repository previously included self-hosted runner setup scripts; these were removed to simplify the workflow. Use the local script or UI instead.

4) Start the optional deploy server (only if you want a server-driven flow):
```bash
cd deploy-ui
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate
# Install required packages directly (no requirements.txt in this folder)
pip install fastapi uvicorn[standard] httpx pydantic
uvicorn deploy-ui.server:app --host 0.0.0.0 --port 9000
```

5) Use the PowerShell script or static UI to deploy:

PowerShell (recommended on Windows):
```powershell
.\deploy-ui\deploy-minikube.ps1 -Image 'youruser/minikube-exercise-app:v20260822-ab12c3d'
```

Browser static UI (optional server flow): open `deploy-ui/local_deploy.html`, enter the image, and point the UI at `http://localhost:9000` if you are using the optional server.

How the workflows tag and push images
- The CI workflow creates a tag of the form `v{YYYYMMDDHHMMSS}-{shortSHA}` and pushes that tag and `latest` to Docker Hub. The manual deploy workflow expects a full image name (e.g., `youruser/minikube-exercise-app:v20260822...`) as input.

Hosts and access
- If using `LoadBalancer` with Minikube, run `minikube tunnel` on the Minikube machine to allocate an external IP, then map `my-minikubeapp.com` to that IP in your hosts file using the provided helper scripts.
- If you use Ingress, enable `minikube addons enable ingress` and map `my-minikubeapp.com` to the Minikube IP.

Security
- Keep `GITHUB_TOKEN` and Docker Hub credentials secret. Use the server approach to avoid pasting tokens into public browsers. Run the server only on trusted machines.

Troubleshooting
- If a local deploy fails: check `kubectl get pods -A` and `kubectl describe deployment <name>` for errors, and run `kubectl logs` on the failing pod.
- If images fail to load into Minikube: ensure Docker and Minikube are installed and reachable; run `minikube image load <image>` manually to validate network access.
- If `my-minikubeapp.com` is unreachable: confirm `kubectl get svc` shows an external IP or enable Ingress; check `/etc/hosts` entries.

Files of interest
- `App/app.py` — FastAPI application
- `App/Dockerfile` — builds the app container
- `Infrastructure/deployment.yaml.template` — deployment template with `IMAGE_PLACEHOLDER`
- `.github/workflows/publish-dockerhub.yml` — CI builder
- `deploy-ui/server.py` — optional backend deploy server
- `deploy-ui/deploy-minikube.ps1` — PowerShell helper script to generate and apply manifests and open Swagger
- `deploy-ui/local_deploy.html` — simple static browser UI to trigger local deploys

Next steps and improvements
- Secure the deploy server with basic auth or local-only binding and firewall rules.
- Add automated tests that run the entire end-to-end flow on a dedicated test Minikube instance.
- Add support for GitHub Container Registry or multi-registry publishing.

If you want, I can implement any of the next-steps above (secure server, automated tests, registry support). Just tell me which one to start with.



