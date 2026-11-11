param(
    [ValidateSet('View','Train','Evaluate','All')][string]$Mode = 'View',
    [ValidateSet('basic','priority','adaptive')][string]$Variant = 'adaptive',
    [int]$Episodes = 30,
    [ValidateSet('balanced','vehicle-heavy','ped-burst')][string]$TrafficProfile = 'ped-burst',
    [string]$ModelPath = '',
    [string]$OutputPath = '',
    [int]$Delay = 80
)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskPython = Join-Path $PSScriptRoot '..\..\.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
}
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = (Get-Command python -ErrorAction Stop).Source }
$runner = Join-Path $PSScriptRoot 'run.py'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$model = if ($ModelPath) { $ModelPath } else { Join-Path $PSScriptRoot "results\train-$Variant\model.pt" }
function Invoke-CrossingPython([string[]]$CommandArguments) {
    & $taskPython $runner @CommandArguments
    if ($LASTEXITCODE -ne 0) { throw "Two-junction command failed with exit code $LASTEXITCODE. See its run folder." }
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'network\corridor.net.xml'))) {
    Invoke-CrossingPython @('build')
}
switch ($Mode) {
    'View' {
        $output = if ($OutputPath) { $OutputPath } else { Join-Path $PSScriptRoot "results\view-$stamp" }
        Invoke-CrossingPython @('view','--model',$model,'--profiles',$TrafficProfile,'--seeds','1001','--delay',"$Delay",'--out',$output)
    }
    'Train' {
        $output = if ($OutputPath) { $OutputPath } else { Join-Path $PSScriptRoot "results\new-$Variant-$stamp" }
        Invoke-CrossingPython @('train','--variant',$Variant,'--episodes',"$Episodes",'--out',$output)
        Write-Host "Saved model: $output\model.pt"
    }
    'Evaluate' {
        $output = if ($OutputPath) { $OutputPath } else { Join-Path $PSScriptRoot "results\evaluation-$Variant-$stamp" }
        Invoke-CrossingPython @('evaluate','--model',$model,'--out',$output)
    }
    'All' {
        $output = if ($OutputPath) { $OutputPath } else { Join-Path $PSScriptRoot "results\experiment-$stamp" }
        foreach ($condition in @('basic','priority','adaptive')) {
            $training = Join-Path $output "train-$condition"
            Invoke-CrossingPython @('train','--variant',$condition,'--episodes',"$Episodes",'--out',$training)
            Invoke-CrossingPython @('evaluate','--model',(Join-Path $training 'model.pt'),'--out',(Join-Path $output "eval-$condition"))
        }
        Invoke-CrossingPython @('baselines','--out',(Join-Path $output 'baselines'))
        Invoke-CrossingPython @('view','--model',(Join-Path $output 'train-adaptive\model.pt'),'--profiles',$TrafficProfile,
                              '--seeds','1001','--delay',"$Delay",'--out',(Join-Path $output 'view'))
    }
}
