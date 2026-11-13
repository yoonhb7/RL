param(
    [ValidateSet('Doctor','Build','View','Train','Evaluate','Calibrate','Pilot','Team','Report')][string]$Mode='Doctor',
    [ValidateSet('low','medium','high')][string]$Level='medium',
    [ValidateSet('dqn','double','dueling','d3qn')][string]$Algorithm='dqn',
    [ValidateSet('wtmin','asmax','ttmin','ctmax','wctmax','tmqmax')][string]$Reward='wtmin',
    [int]$Seed=11,
    [int]$Episodes=100,
    [ValidateSet('fixed','queue')][string]$Controller='fixed',
    [ValidateSet('A','B','C')][string]$Owner='A',
    [int]$Delay=70,
    [string]$ModelPath='',
    [string]$OutputPath='',
    [string]$ConfigPath='configs/shared.json'
)
$ErrorActionPreference='Stop'
$taskVenv=Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$taskBundled=Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if(Test-Path -LiteralPath $taskVenv){$taskPython=$taskVenv}
elseif(Test-Path -LiteralPath $taskBundled){$taskPython=$taskBundled}
else{$taskPython=(Get-Command python -ErrorAction Stop).Source}
Push-Location $PSScriptRoot
$env:MPLCONFIGDIR=Join-Path $PSScriptRoot 'tmp/matplotlib'
try{
    if($Mode -eq 'View'){
        & $taskPython 'runtime_check.py' --gui
        if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
        Write-Output 'Opening SUMO. No further console input is needed.'
    }
    $taskArgs=@('start.py','--config',$ConfigPath)
    $taskTime=Get-Date -Format 'yyyyMMdd-HHmmss'
    switch($Mode){
        'Doctor' {$taskArgs+=@('doctor')}
        'Build' {$taskArgs+=@('build')}
        'Train' {
            if(!$OutputPath){$OutputPath="results/manual/$Level-$Reward-$Algorithm-seed$Seed-$taskTime"}
            $taskArgs+=@('train','--level',$Level,'--algorithm',$Algorithm,'--reward',$Reward,'--seed',"$Seed",'--episodes',"$Episodes",'--out',$OutputPath)
        }
        'View' {
            if(!$OutputPath){$OutputPath="results/view/$Level-$taskTime"}
            $taskArgs+=@('view','--levels',$Level,'--seeds','1001','--delay',"$Delay",'--out',$OutputPath)
            if($ModelPath){$taskArgs+=@('--model',$ModelPath)}else{$taskArgs+=@('--controller',$Controller)}
        }
        'Evaluate' {
            if(!$OutputPath){$OutputPath="results/evaluate/$taskTime"}
            $taskArgs+=@('evaluate','--levels','low','medium','high','--seeds','1001','1002','1003','1004','1005','--out',$OutputPath)
            if($ModelPath){$taskArgs+=@('--model',$ModelPath)}else{$taskArgs+=@('--controller',$Controller)}
        }
        'Calibrate' {
            if(!$OutputPath){$OutputPath="results/calibration/$taskTime"}
            $taskArgs+=@('calibrate','--out',$OutputPath)
        }
        'Pilot' {
            $taskArgs=@('start.py','--config','configs/pilot.json','batch','--plan','configs/pilot-plan.json','--out','results/pilot-v3')
        }
        'Team' {
            if(!$OutputPath){$OutputPath="results/team-$Owner"}
            $taskArgs+=@('batch','--plan','configs/team-plan.json','--owner',$Owner,'--out',$OutputPath)
        }
        'Report' {
            if(!$OutputPath){$OutputPath='results/pilot-report'}
            if(Test-Path -LiteralPath 'results/pilot-v3'){
                $taskArgs+=@('report','--roots','results/pilot-v3','results/pilot-baselines-v3','--out',$OutputPath)
            }else{
                $taskArgs+=@('report','--roots','results/pilot-v2','results/pilot-baselines-v2','--out',$OutputPath)
            }
        }
    }
    & $taskPython @taskArgs
    if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
}finally{Pop-Location}
