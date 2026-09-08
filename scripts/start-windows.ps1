$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

$ImageName     = "jobfit:latest"
$ContainerName = "jobfit"
$VolumeName    = "jobfit-data"
$Port          = if ($env:JOBFIT_PORT) { $env:JOBFIT_PORT } else { "8000" }

docker build -t $ImageName .
docker rm -f $ContainerName 2>$null | Out-Null

$EnvArgs = @()
if (Test-Path .env) {
  $EnvArgs = @("--env-file", ".env")
}

docker run -d `
  --name $ContainerName `
  -p "$($Port):8000" `
  -v "$($VolumeName):/data" `
  @EnvArgs `
  $ImageName | Out-Null

Write-Host "JobFit is running on http://localhost:$Port"
