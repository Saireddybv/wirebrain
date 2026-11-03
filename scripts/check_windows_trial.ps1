param([Parameter(Mandatory)][string]$OutputFile, [string]$Baseline)
$ErrorActionPreference = 'Stop'
$key = Get-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
$connections = Get-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings\Connections'
$state = [ordered]@{}
foreach ($name in 'ProxyEnable','ProxyServer','ProxyOverride','AutoConfigURL') { $state[$name] = $key.GetValue($name) }
foreach ($name in 'DefaultConnectionSettings','SavedLegacySettings') {
    $bytes = $connections.GetValue($name)
    $state[$name] = if ($bytes) { [Convert]::ToBase64String($bytes) }
}
foreach ($scope in 'CurrentUser','LocalMachine') {
    $state["${scope}Roots"] = @(Get-ChildItem "Cert:\$scope\Root" | Select-Object -ExpandProperty Thumbprint | Sort-Object)
}
$state['RedirectorProcesses'] = @(Get-Process -Name windows-redirector -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id | Sort-Object)
$state['Drivers'] = @(Get-CimInstance Win32_SystemDriver | Where-Object { $_.Name -match 'WinDivert|mitmproxy' } | Sort-Object Name | Select-Object Name,State,StartMode,PathName)
$json = $state | ConvertTo-Json -Depth 5
$json | Set-Content -LiteralPath $OutputFile -Encoding utf8
if ($Baseline -and (Get-Content -Raw -LiteralPath $Baseline).Trim() -ne $json.Trim()) {
    throw 'Trial state differs from baseline. Compare the two JSON files before release.'
}
