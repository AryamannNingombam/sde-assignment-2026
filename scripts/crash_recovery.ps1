param(
    [string]$Url = "http://127.0.0.1:8700",
    [string]$State = "runs/controller_recovery.json"
)

python controller.py $Url --state $State
