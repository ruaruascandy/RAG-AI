param(
    [ValidateSet("auto", "780m", "7900xtx")]
    [string]$Gpu = "auto",
    [string]$Model = "qwen2.5-coder:3b",
    [switch]$SkipWarmup
)

$ErrorActionPreference = "Stop"

$ollamaExe = "F:\Ollama\ollama.exe"
$modelsPath = "F:\ollamaimagers"

if (-not (Test-Path -LiteralPath $ollamaExe)) {
    throw "Ollama executable not found: $ollamaExe"
}

function Normalize-DeviceStatus {
    param([string]$Status)

    if ([string]::IsNullOrWhiteSpace($Status)) {
        return ""
    }

    $s = $Status.Trim().ToLowerInvariant()
    if ($s -match "started|ok|running|up|online") {
        return "Started"
    }
    if ($s -match "disconnected|not present|missing|disabled|offline") {
        return "Disconnected"
    }

    return $Status.Trim()
}

function Get-DisplayStatus {
    $entries = @()

    # Prefer Get-PnpDevice because it is less locale-sensitive.
    try {
        $pnp = Get-PnpDevice -Class Display -ErrorAction Stop
        foreach ($item in $pnp) {
            $name = if (-not [string]::IsNullOrWhiteSpace($item.FriendlyName)) { $item.FriendlyName } else { $item.Name }
            $entries += [pscustomobject]@{
                InstanceId = $item.InstanceId
                Description = $name
                Status = Normalize-DeviceStatus -Status $item.Status
            }
        }
        if ($entries.Count -gt 0) {
            return $entries
        }
    } catch {
        # Fall back to pnputil output parsing.
    }

    $raw = & pnputil /enum-devices /class Display
    $entries = @()
    $current = @{}

    foreach ($line in $raw) {
        if ($line -match "^\s*Instance ID:\s*(.+)$") {
            if ($current.Count -gt 0) {
                $entries += [pscustomobject]$current
                $current = @{}
            }
            $current.InstanceId = $matches[1].Trim()
        } elseif ($line -match "^\s*Device Description:\s*(.+)$") {
            $current.Description = $matches[1].Trim()
        } elseif ($line -match "^\s*Status:\s*(.+)$") {
            $current.Status = Normalize-DeviceStatus -Status $matches[1].Trim()
        }
    }

    if ($current.Count -gt 0) {
        $entries += [pscustomobject]$current
    }

    return $entries
}

function Get-StatusText {
    param($Device)

    if ($null -eq $Device) {
        return "(not found)"
    }
    if ([string]::IsNullOrWhiteSpace($Device.Status)) {
        return "(unknown)"
    }
    return $Device.Status
}

$display = Get-DisplayStatus
$rx7900 = $display | Where-Object { $_.Description -like "*RX 7900 XTX*" } | Select-Object -First 1
$r780m = $display | Where-Object { $_.Description -like "*Radeon 780M*" } | Select-Object -First 1

Write-Host "RX 7900 XTX status: $(Get-StatusText $rx7900)"
Write-Host "Radeon 780M status: $(Get-StatusText $r780m)"

if ($Gpu -eq "7900xtx") {
    if ($null -eq $rx7900) {
        throw "RX 7900 XTX was not detected."
    }
    if ($rx7900.Status -eq "Disconnected") {
        throw "RX 7900 XTX is disconnected. Please reconnect or enable it first."
    }
    if (-not [string]::IsNullOrWhiteSpace($rx7900.Status) -and $rx7900.Status -ne "Started") {
        throw "RX 7900 XTX is not in Started state. Current status: $($rx7900.Status)."
    }
    if ([string]::IsNullOrWhiteSpace($rx7900.Status)) {
        Write-Warning "RX 7900 XTX status is unknown. Continuing anyway."
    }
}

if ($Gpu -eq "780m") {
    if ($null -eq $r780m) {
        throw "Radeon 780M was not detected."
    }
    if ($r780m.Status -eq "Disconnected") {
        throw "Radeon 780M is disconnected. Please enable or reconnect it first."
    }
    if (-not [string]::IsNullOrWhiteSpace($r780m.Status) -and $r780m.Status -ne "Started") {
        throw "Radeon 780M is not in Started state. Current status: $($r780m.Status)."
    }
    if ([string]::IsNullOrWhiteSpace($r780m.Status)) {
        Write-Warning "Radeon 780M status is unknown. Continuing anyway."
    }
}

Get-Process -Name "ollama app" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process -Name "ollama" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 700

# Keep runtime clean: use Vulkan and remove conflicting ROCm/HIP overrides.
$env:OLLAMA_MODELS = $modelsPath
$env:OLLAMA_VULKAN = "1"
Remove-Item Env:OLLAMA_LLM_LIBRARY -ErrorAction SilentlyContinue
Remove-Item Env:HIP_VISIBLE_DEVICES -ErrorAction SilentlyContinue
Remove-Item Env:HSA_OVERRIDE_GFX_VERSION -ErrorAction SilentlyContinue
Remove-Item Env:ROCR_VISIBLE_DEVICES -ErrorAction SilentlyContinue

switch ($Gpu) {
    "780m" {
        $env:GGML_VK_VISIBLE_DEVICES = "0"
        Write-Host "Using Vulkan device index 0 for 780M profile."
    }
    "7900xtx" {
        # If both GPUs are started, 7900XTX is typically index 1.
        if ($r780m -and $r780m.Status -eq "Started") {
            $env:GGML_VK_VISIBLE_DEVICES = "1"
        } else {
            $env:GGML_VK_VISIBLE_DEVICES = "0"
        }
        Write-Host "Using Vulkan device index $($env:GGML_VK_VISIBLE_DEVICES) for 7900XTX profile."
    }
    default {
        Remove-Item Env:GGML_VK_VISIBLE_DEVICES -ErrorAction SilentlyContinue
        Write-Host "Using automatic Vulkan device selection."
    }
}

$server = Start-Process -FilePath $ollamaExe -ArgumentList "serve" -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 2

Write-Host "Started Ollama server (PID=$($server.Id)) with mode: $Gpu"

if (-not $SkipWarmup) {
    Write-Host "Running warmup model call: $Model"
    & $ollamaExe run $Model "ok" | Out-Null
}

& $ollamaExe ps

Write-Host ""
Write-Host "Tip: stop with: Get-Process ollama -ErrorAction SilentlyContinue | Stop-Process -Force"
