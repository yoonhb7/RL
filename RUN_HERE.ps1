param(
    [ValidateSet('Doctor', 'View', 'Evaluate', 'Train')][string]$Mode = 'Doctor',
    [ValidateSet('toy', 'corridor2', 'corridor3')][string]$Scenario = 'toy',
    [ValidateSet('fixed', 'queue', 'dqn')][string]$Controller = 'dqn',
    [int]$Episodes = 20,
    [int]$Delay = 1000,
    [string]$ModelPath = '',
    [string]$OutputPath = ''
)
$ErrorActionPreference = 'Stop'
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) {
    $taskPython = $venvPython
} elseif (Test-Path -LiteralPath $bundledPython) {
    $taskPython = $bundledPython
} else {
    throw 'Install Python and follow README.md; or create .venv first.'
}
$runner = Join-Path $PSScriptRoot 'local_runtime.py'
$scenarioPath = "sumo/$Scenario"
$chosenModel = if ($ModelPath) { $ModelPath } else { "results/verified/$Scenario-train/model.pt" }
$chosenOutput = if ($OutputPath) { $OutputPath } else {
    switch ($Mode) {
        'View' { "results/local/$Scenario-view" }
        'Evaluate' { "results/local/$Scenario-evaluation" }
        'Train' { "results/local/$Scenario-train" }
    }
}
switch ($Mode) {
    'Doctor' { & $taskPython $runner doctor }
    'View' { & $taskPython $runner view --scenario $scenarioPath --controllers $Controller --model $chosenModel --seeds 1001 --out $chosenOutput --delay $Delay }
    'Evaluate' { & $taskPython $runner evaluate --scenario $scenarioPath --controllers fixed queue dqn --model $chosenModel --seeds 1001 1002 1003 1004 1005 --out $chosenOutput }
    'Train' { & $taskPython $runner train --scenario $scenarioPath --episodes $Episodes --out $chosenOutput }
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
