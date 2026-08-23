import os
import time
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Deploy UI Server")

DOCKERHUB_USERNAME = os.environ.get("DOCKERHUB_USERNAME")
DOCKERHUB_TOKEN = os.environ.get("DOCKERHUB_TOKEN")


@app.get("/tags")
async def get_tags(repo: str):
    if '/' not in repo:
        raise HTTPException(status_code=400, detail="repo must be user/repo")
    user, name = repo.split('/', 1)
    url = f"https://hub.docker.com/v2/repositories/{user}/{name}/tags?page_size=100"
    headers = {}
    async with httpx.AsyncClient(timeout=20) as client:
        # If Docker Hub credentials are available as env vars, obtain a JWT token and use it
        if DOCKERHUB_USERNAME and DOCKERHUB_TOKEN:
            try:
                auth_resp = await client.post('https://hub.docker.com/v2/users/login/', json={ 'username': DOCKERHUB_USERNAME, 'password': DOCKERHUB_TOKEN })
                if auth_resp.status_code == 200:
                    token = auth_resp.json().get('token')
                    if token:
                        headers['Authorization'] = f"JWT {token}"
            except Exception:
                # ignore auth failure and continue unauthenticated
                pass

        r = await client.get(url, headers=headers)
        if r.status_code != 200:
            # try to surface any error message
            detail = None
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            raise HTTPException(status_code=502, detail=f"Docker Hub API returned {r.status_code}: {detail}")
        data = r.json()
        results = [ { 'name': t['name'], 'last_updated': t.get('last_updated'), 'full_size': t.get('full_size') } for t in data.get('results', []) ]
        return { 'results': results }


class DispatchRequest(BaseModel):
    image: str


class DeployLocalRequest(BaseModel):
    image: str


@app.post("/dispatch")
async def dispatch(req: DispatchRequest):
    # extract local deploy logic to helper and call it
    return await _local_deploy(req.image)


async def _local_deploy(image: str):
    import subprocess, shutil, json, tempfile

    def run_cmd(cmd, check=True):
        proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return proc

    IMAGE = image
    # 1) Try docker pull
    docker_available = shutil.which('docker') is not None
    minikube_available = shutil.which('minikube') is not None
    pull_errors = []
    # If minikube is available, ensure it's running (start if necessary)
    if minikube_available:
        try:
            s = run_cmd('minikube status')
            out = (s.stdout or '') + (s.stderr or '')
            if 'Running' not in out:
                # attempt to start minikube
                run_cmd('minikube start')
                # wait until status shows Running
                for _ in range(30):
                    s2 = run_cmd('minikube status')
                    o2 = (s2.stdout or '') + (s2.stderr or '')
                    if 'Running' in o2:
                        break
                    time.sleep(2)
        except Exception:
            pass
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
