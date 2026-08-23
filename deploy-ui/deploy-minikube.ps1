param(
    [string]$Image,
    [string]$DockerUsername,
    [string]$DockerPassword
)

if (-not $Image) {
    $Image = Read-Host "Enter Docker image (owner/repo:tag)"
}

# Allow picking credentials from environment variables if not passed as params
if (-not $DockerUsername) { $DockerUsername = $env:DOCKERHUB_USERNAME }
if (-not $DockerPassword) { $DockerPassword = $env:DOCKERHUB_TOKEN }

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot = Resolve-Path (Join-Path $scriptDir '..')
$infra = Join-Path $repoRoot 'Infrastructure'
$gen = Join-Path $repoRoot 'generated-manifests'
New-Item -ItemType Directory -Path $gen -Force | Out-Null

$deployTemplate = Join-Path $infra 'deployment.yaml.template'
$deployOut = Join-Path $gen 'deployment.yaml'
if (-not (Test-Path $deployTemplate)) {
    Write-Error "Deployment template not found: $deployTemplate"
    exit 1
}

Write-Host "Generating deployment manifest with image: $Image"
(Get-Content $deployTemplate) -replace 'IMAGE_PLACEHOLDER',$Image | Set-Content $deployOut

Copy-Item (Join-Path $infra 'service.yaml') $gen -Force
if (Test-Path (Join-Path $infra 'ingress.yaml')) {
    Copy-Item (Join-Path $infra 'ingress.yaml') $gen -Force
}

Write-Host "Applying manifests to cluster..."
kubectl apply -f $gen

# If Docker Hub credentials provided, create/update imagePullSecret in the cluster
$credsProvided = $false
if ($DockerUsername -and $DockerPassword) {
    $credsProvided = $true
    Write-Host "Creating/updating imagePullSecret 'regcred' using provided Docker Hub credentials"
    $secretCmd = "kubectl create secret docker-registry regcred --docker-server=https://index.docker.io/v1/ --docker-username='$DockerUsername' --docker-password='$DockerPassword' --dry-run=client -o yaml | kubectl apply -f -"
    Invoke-Expression $secretCmd
}

# Extract deployment name from generated deployment manifest
$deployContent = Get-Content $deployOut -Raw
$deployName = $null
if ($deployContent -match '(?s)kind:\s*Deployment.*?metadata:.*?name:\s*(\S+)') {
    $deployName = $matches[1]
}

if ($deployName) {
    Write-Host "Waiting for rollout of deployment: $deployName"
    # If credentials were provided, patch the deployment to reference the imagePullSecret
    if ($credsProvided) {
        Write-Host "Patching deployment to use imagePullSecrets 'regcred'"
        $patch = '{"spec":{"template":{"spec":{"imagePullSecrets":[{"name":"regcred"}]}}}}'
        kubectl patch deployment/$deployName -p $patch | Out-Null
    }

    kubectl rollout status deployment/$deployName --timeout=120s
} else {
    Write-Warning "Could not determine deployment name from manifest. Skipping rollout wait."
}

# Determine service URL via minikube
$serviceOut = Join-Path $gen 'service.yaml'
$serviceName = $null
if (Test-Path $serviceOut) {
    $serviceContent = Get-Content $serviceOut -Raw
    if ($serviceContent -match '(?s)metadata:.*?name:\s*(\S+)') { $serviceName = $matches[1] }
}

$serviceUrl = $null
if ($serviceName) {
    Write-Host "Retrieving service URL for: $serviceName"
    try {
        $serviceUrl = & minikube service $serviceName --url 2>$null
    } catch {
        $serviceUrl = $null
    }
}

if (-not $serviceUrl) {
    Write-Warning "minikube service URL not available. You can access the app via ingress or node port."
} else {
    $serviceUrl = $serviceUrl.Trim()
    $docsUrl = ($serviceUrl.TrimEnd('/')) + '/docs'
    Write-Host "Opening Swagger UI: $docsUrl"
    Start-Process $docsUrl
}

Write-Host "Done."
