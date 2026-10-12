param(
    [string]$Payload
)
# Windows toast notifier. Deliberately ASCII-only so PowerShell 5.1
# never mis-decodes this file as ANSI. All Chinese text arrives via the
# UTF-8 JSON payload file (title / body), never via command line args.
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Payload)) {
    $Payload = Join-Path $PSScriptRoot "state\notify.json"
}
$resultFile = Join-Path (Split-Path -Parent $Payload) "notify-result.txt"
$utf8 = New-Object System.Text.UTF8Encoding($false)

try {
    $raw = [System.IO.File]::ReadAllText($Payload, [System.Text.Encoding]::UTF8)
    $obj = $raw | ConvertFrom-Json

    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] | Out-Null

    $tpl = '<toast><visual><binding template="ToastGeneric"><text></text><text></text></binding></visual></toast>'
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml($tpl)
    $nodes = $xml.GetElementsByTagName("text")
    $nodes.Item(0).AppendChild($xml.CreateTextNode([string]$obj.title)) | Out-Null
    $nodes.Item(1).AppendChild($xml.CreateTextNode([string]$obj.body)) | Out-Null

    $toast = New-Object Windows.UI.Notifications.ToastNotification $xml
    $appId = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)

    [System.IO.File]::WriteAllText($resultFile, "OK", $utf8)
}
catch {
    [System.IO.File]::WriteAllText($resultFile, "FAIL: " + $_.Exception.Message, $utf8)
}
