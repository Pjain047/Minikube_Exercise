import os
import time
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Deploy UI Server")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")


@app.get("/tags")
async def get_tags(repo: str):
    if '/' not in repo:
        raise HTTPException(status_code=400, detail="repo must be user/repo")
    user, name = repo.split('/', 1)
    url = f"https://hub.docker.com/v2/repositories/{user}/{name}/tags?page_size=100"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Docker Hub API returned {r.status_code}")
        data = r.json()
        results = [ { 'name': t['name'], 'last_updated': t.get('last_updated'), 'full_size': t.get('full_size') } for t in data.get('results', []) ]
        return { 'results': results }


class DispatchRequest(BaseModel):
    owner: str
    repo: str
    image: str
    ref: Optional[str] = 'main'
    mode: Optional[str] = None  # 'local' or 'github'


@app.post("/dispatch")
async def dispatch(req: DispatchRequest):
    mode = (req.mode or os.environ.get('DEPLOY_MODE') or 'local').lower()

    if mode == 'github':
        if not GITHUB_TOKEN:
            raise HTTPException(status_code=500, detail="Server missing GITHUB_TOKEN environment variable for github mode")

        headers = { 'Authorization': f'token {GITHUB_TOKEN}', 'Accept': 'application/vnd.github.v3+json' }
        dispatch_url = f"https://api.github.com/repos/{req.owner}/{req.repo}/actions/workflows/manual-deploy-minikube.yml/dispatches"
        body = { 'ref': req.ref, 'inputs': { 'image': req.image } }

        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(dispatch_url, json=body, headers=headers)
            if r.status_code not in (204, 201):
                detail = await r.text()
                raise HTTPException(status_code=502, detail=f"Dispatch failed {r.status_code}: {detail}")

        # fallback to previous behavior: find run and poll
        runs_url = f"https://api.github.com/repos/{req.owner}/{req.repo}/actions/workflows/manual-deploy-minikube.yml/runs?per_page=20"
        actor = None
        async with httpx.AsyncClient(timeout=10) as client:
            u = await client.get('https://api.github.com/user', headers=headers)
            if u.status_code == 200:
                actor = u.json().get('login')

        run = None
        start = time.time()
        timeout = 60
        async with httpx.AsyncClient(timeout=20) as client:
            while time.time() - start < timeout:
                r = await client.get(runs_url, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    for candidate in data.get('workflow_runs', []):
                        if actor and candidate.get('actor', {}).get('login') == actor:
                            run = candidate
                            break
                    if not run and data.get('workflow_runs'):
                        run = data['workflow_runs'][0]
                    if run:
                        break
                await httpx.sleep(3)

        if not run:
            raise HTTPException(status_code=504, detail='Workflow run not found after dispatch')

        run_id = run['id']
        run_url = f"https://api.github.com/repos/{req.owner}/{req.repo}/actions/runs/{run_id}"

        # poll until complete
        end_time = time.time() + 20*60
        final = None
        async with httpx.AsyncClient(timeout=20) as client:
            while time.time() < end_time:
                r = await client.get(run_url, headers=headers)
                if r.status_code == 200:
                    j = r.json()
                    if j.get('status') == 'completed':
                        final = j
                        break
                await httpx.sleep(5)

        if not final:
            raise HTTPException(status_code=504, detail='Timed out waiting for workflow run to complete')

        host = 'http://my-minikubeapp.com'
        health = None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                h = await client.get(f"{host}/health")
                health = { 'status': h.status_code, 'body': h.text }
        except Exception as e:
            health = { 'error': str(e) }

        return {
            'conclusion': final.get('conclusion'),
            'run_id': run_id,
            'run_number': final.get('run_number'),
            'host': host,
            'version': req.image,
            'health': health,
            'run_url': final.get('html_url')
        }

    # local deploy mode: run commands on this machine to load image into minikube and apply manifests
    # This requires kubectl and minikube (or docker) installed on the server host.
    IMAGE = req.image
    import subprocess, shutil, json, tempfile

    def run_cmd(cmd, check=True):
        proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return proc

    # 1) Try docker pull
    docker_available = shutil.which('docker') is not None
    minikube_available = shutil.which('minikube') is not None
    pull_errors = []
    if docker_available:
        p = run_cmd(f"docker pull {IMAGE}")
        if p.returncode != 0:
            pull_errors.append(p.stderr.strip())

    # 2) Try minikube image load
    load_ok = False
    if minikube_available:
        p = run_cmd(f"minikube image load {IMAGE}")
        if p.returncode == 0:
            load_ok = True

    # 3) If minikube not available or load failed, but docker pulled, attempt docker save -> minikube image load (if minikube present)
    if not load_ok and minikube_available and docker_available:
        try:
            tf = tempfile.NamedTemporaryFile(delete=False, suffix='.tar')
            tf.close()
            save_cmd = f"docker save {IMAGE} -o {tf.name}"
            p = run_cmd(save_cmd)
            if p.returncode == 0:
                p2 = run_cmd(f"minikube image load {tf.name}")
                if p2.returncode == 0:
                    load_ok = True
            run_cmd(f"rm -f {tf.name}")
        except Exception as e:
            pull_errors.append(str(e))

    # 4) Prepare manifests
    gen_dir = os.path.join(os.getcwd(), 'generated-manifests')
    os.makedirs(gen_dir, exist_ok=True)
    tpl = os.path.join(os.getcwd(), '..', 'Infrastructure', 'deployment.yaml.template')
    # allow relative path if running repo root
    if not os.path.exists(tpl):
        tpl = os.path.join(os.getcwd(), 'Infrastructure', 'deployment.yaml.template')
    with open(tpl, 'r') as f:
        content = f.read()
    content = content.replace('IMAGE_PLACEHOLDER', IMAGE)
    deploy_path = os.path.join(gen_dir, 'deployment.yaml')
    with open(deploy_path, 'w') as f:
        f.write(content)
    # copy service and ingress
    for name in ('Infrastructure/service.yaml', 'Infrastructure/ingress.yaml'):
        if os.path.exists(name):
            shutil.copy(name, gen_dir)
        else:
            # try parent path
            alt = os.path.join(os.getcwd(), '..', name)
            if os.path.exists(alt):
                shutil.copy(alt, gen_dir)

    # 5) kubectl apply
    p = run_cmd(f"kubectl apply -f {gen_dir}")
    if p.returncode != 0:
        raise HTTPException(status_code=500, detail=f"kubectl apply failed: {p.stderr}")

    # 6) wait for rollout
    p = run_cmd("kubectl rollout status deployment/minikube-app --timeout=120s")
    if p.returncode != 0:
        # continue but report
        rollout_msg = p.stderr.strip()
    else:
        rollout_msg = p.stdout.strip()

    # 7) get service info
    p = run_cmd("kubectl get svc minikube-app-service -o json")
    host = 'http://my-minikubeapp.com'
    svc_info = None
    if p.returncode == 0:
        try:
            svc_info = json.loads(p.stdout)
            # try to get external IP
            status = svc_info.get('status', {})
            ingress = status.get('loadBalancer', {}).get('ingress', [])
            if ingress and isinstance(ingress, list):
                ip = ingress[0].get('ip') or ingress[0].get('hostname')
                if ip:
                    host = f"http://{ip}"
        except Exception:
            pass

    # 8) health check
    health = None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            h = await client.get(f"{host}/health")
            health = { 'status': h.status_code, 'body': h.text }
    except Exception as e:
        health = { 'error': str(e) }

    return {
        'conclusion': 'local-deploy',
        'host': host,
        'version': IMAGE,
        'health': health,
        'rollout': rollout_msg,
        'pull_errors': pull_errors,
        'svc': svc_info
    }
