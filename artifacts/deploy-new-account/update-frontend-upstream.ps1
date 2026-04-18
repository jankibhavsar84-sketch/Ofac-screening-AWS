param(
  [string]$Profile = "ofac-deploy",
  [string]$Region = "us-east-2",
  [string]$Cluster = "Screening",
  [string]$BackendService = "ofac-screening-backend-svc",
  [string]$FrontendService = "ofac-screening-frontend-svc",
  [string]$TaskDefPath = "artifacts/deploy-new-account/frontend-task-definition.json"
)

$backendTasks = aws ecs list-tasks --cluster $Cluster --service-name $BackendService --profile $Profile --region $Region --query 'taskArns' --output json | ConvertFrom-Json
if ($backendTasks.Count -lt 1) { throw "No backend task found for $BackendService" }
$backendDesc = aws ecs describe-tasks --cluster $Cluster --tasks $backendTasks --profile $Profile --region $Region --output json | ConvertFrom-Json
$eniId = $backendDesc.tasks[0].attachments[0].details | Where-Object { $_.name -eq 'networkInterfaceId' } | Select-Object -ExpandProperty value
if (-not $eniId) { throw "Could not resolve backend ENI" }
$backendIp = aws ec2 describe-network-interfaces --network-interface-ids $eniId --profile $Profile --region $Region --query 'NetworkInterfaces[0].PrivateIpAddress' --output text
if (-not $backendIp -or $backendIp -eq 'None') { throw "Could not resolve backend private IP" }

$taskDef = Get-Content $TaskDefPath -Raw | ConvertFrom-Json
$updated = $false
foreach ($env in $taskDef.containerDefinitions[0].environment) {
  if ($env.name -eq 'BACKEND_UPSTREAM') {
    $env.value = ("http://{0}:8000" -f $backendIp)
    $updated = $true
  }
}
if (-not $updated) {
  $taskDef.containerDefinitions[0].environment += (New-Object PSObject -Property @{ name = 'BACKEND_UPSTREAM'; value = ("http://{0}:8000" -f $backendIp) })
}
$taskDef | ConvertTo-Json -Depth 20 | Set-Content $TaskDefPath

$newTaskDefArn = aws ecs register-task-definition --cli-input-json ("file://" + (Resolve-Path $TaskDefPath).Path) --profile $Profile --region $Region --query 'taskDefinition.taskDefinitionArn' --output text
if ($LASTEXITCODE -ne 0) { throw "Failed to register frontend task definition" }

aws ecs update-service --cluster $Cluster --service $FrontendService --task-definition $newTaskDefArn --force-new-deployment --profile $Profile --region $Region --query 'service.serviceArn' --output text | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to update frontend service" }

Write-Host "Frontend upstream updated to backend IP: $backendIp"
Write-Host "New frontend task definition: $newTaskDefArn"
