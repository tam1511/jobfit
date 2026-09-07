$ErrorActionPreference = "Stop"

$ContainerName = "jobfit"

docker rm -f $ContainerName 2>$null | Out-Null
Write-Host "JobFit stopped."
