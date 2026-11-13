param([string]$Choice='')
$ErrorActionPreference='Stop'
Write-Output 'Single-intersection SUMO simulation (view a trained pilot model)'
Write-Output '1 = LOW, 2 = MEDIUM, 3 = HIGH'
if(!$Choice){$Choice=Read-Host 'Choose traffic level [2]'}
if(!$Choice){$Choice='2'}
if($Choice -notin @('1','2','3')){Write-Error 'Choose 1, 2, or 3.';exit 1}
$taskLevel=@{'1'='low';'2'='medium';'3'='high'}[$Choice]
$taskModel=Join-Path $PSScriptRoot "results/demo-models/$taskLevel/model.pt"
Write-Output "Traffic: $taskLevel. SUMO will open automatically."
Write-Output 'If covered by another window, select SUMO on the taskbar or use Alt+Tab.'
if(Test-Path -LiteralPath $taskModel){
    Write-Output 'Controller: trained Double DQN pilot (no training in this view).'
    & (Join-Path $PSScriptRoot 'RUN_HERE.ps1') -Mode View -Level $taskLevel -ConfigPath configs/pilot.json -ModelPath $taskModel
}else{
    Write-Output 'Pilot checkpoint missing. Showing the fixed-time reference controller.'
    & (Join-Path $PSScriptRoot 'RUN_HERE.ps1') -Mode View -Level $taskLevel -Controller fixed
}
exit $LASTEXITCODE
