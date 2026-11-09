param(
    [string]$Scenario = "scenarios/public_03_load.yaml",
    [string]$RunDir = "runs/base_public_03"
)

$timer = [Diagnostics.Stopwatch]::StartNew()
python -m sim baseline --scenario $Scenario --run-dir $RunDir
$timer.Stop()
$size = (Get-ChildItem $RunDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Output ("wall_seconds={0:N1} output_bytes={1}" -f $timer.Elapsed.TotalSeconds, $size)
