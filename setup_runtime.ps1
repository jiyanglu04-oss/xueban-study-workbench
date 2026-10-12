# 学伴 · 运行环境自动准备
#
# 第一次运行时由「启动工作台.bat」调用。做的事：
#   下载一个精简的 Python（约 11 MB）解压到项目里的 runtime\ 下，
#   再把抓取需要的 Playwright 装上。
#
# 为什么这么做：对方电脑上不一定有 Python，让他自己去官网装、还要记得勾
# 「Add python.exe to PATH」，十个人里有八个会卡在这一步。现在他只需要
# 双击一下，剩下的这脚本自己办。
#
# 全程不碰系统环境、不改 PATH、不需要管理员权限 ——
# 所有东西都装在本文件夹里，删掉文件夹就等于卸载干净。
#
# 下载源都做了国内镜像回退，按顺序试到通为止。

# 刻意用 Continue 而不是 Stop：curl / pip 这类原生程序会把进度和警告写到
# stderr，Stop 模式下这会被当成致命错误、直接掐断脚本（实测踩过两次）。
# 所以退出码一律由各处自己检查。
$ErrorActionPreference = 'Continue'
$Root = $PSScriptRoot
Set-Location $Root

$PyDir = Join-Path $Root 'runtime\python'
$PyExe = Join-Path $PyDir 'python.exe'
$Tmp   = Join-Path $Root 'runtime\_download'
$Index = 'https://mirrors.aliyun.com/pypi/simple/'

function Say([string]$msg, [string]$color = 'Gray') {
    Write-Host $msg -ForegroundColor $color
}

function Fetch([string]$url, [string]$dest) {
    # curl.exe 从 Win10 1803 起是系统自带的，比 Invoke-WebRequest 快很多。
    # ⚠️ 它会把进度写到 stderr，而 $ErrorActionPreference='Stop' 会把 native 命令的
    # stderr 当成致命错误直接中断脚本 —— 所以这里临时降级成 Continue。
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
        if (Test-Path $curl) {
            & $curl -L --fail --silent --show-error --retry 2 --connect-timeout 20 `
                --max-time 600 -o $dest $url 2>$null
            if ($LASTEXITCODE -ne 0) { return $false }
            return (Test-Path $dest) -and ((Get-Item $dest).Length -gt 100KB)
        }
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
        return (Test-Path $dest) -and ((Get-Item $dest).Length -gt 100KB)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $prevEAP
    }
}

function TryFetchMany([string[]]$urls, [string]$dest, [string]$what) {
    foreach ($u in $urls) {
        $host_ = $u -replace '^https?://([^/]+).*', '$1'
        Say ("    " + $what + "  <- " + $host_)
        if (Fetch $u $dest) { return $true }
        Say "      这个源不通，换下一个…" 'DarkYellow'
    }
    return $false
}

Say ''
Say '  ================================================'
Say '   学伴 · 正在准备运行环境（只需要做这一次）'
Say '  ================================================'
Say '    会下载到本文件夹的 runtime\ 里，不影响你电脑上的其他软件。'
Say ''

if (Test-Path $PyExe) {
    & $PyExe -c "import playwright; import PIL; import winrt.windows.media.ocr; import winrt.windows.graphics.imaging; import winrt.windows.storage" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Say '  运行环境与课表识别组件已就绪。' 'Green'
        exit 0
    }
    Say '  正在补齐课表图片识别组件…'
    & $PyExe -m pip install -r (Join-Path $Root 'sync\requirements.txt') -i $Index --no-warn-script-location --quiet
    if ($LASTEXITCODE -ne 0) { Say '  组件安装失败，请联网后重试。' 'Red'; exit 1 }
    exit 0
}

New-Item -ItemType Directory -Force -Path $Tmp | Out-Null

# ---------------------------------------------------------------- 1. Python
Say '  [1/3] 下载 Python 运行环境（约 11 MB，看网速可能要等 1~3 分钟）'
$zip = Join-Path $Tmp 'python-embed.zip'
# 用 3.11 而不是 3.12：3.12 起官方把 distutils 从标准库移除了，而部分镜像上的
# get-pip.py 还是旧版、恰好依赖它 —— 会以一句 "No module named 'distutils'"
# 失败，非常难查（实测踩过）。3.11 没有这个坑。
$pyVer = '3.11.9'
$pythonUrls = @(
    "https://registry.npmmirror.com/-/binary/python/$pyVer/python-$pyVer-embed-amd64.zip",
    "https://mirrors.huaweicloud.com/python/$pyVer/python-$pyVer-embed-amd64.zip",
    "https://mirrors.aliyun.com/python-release/windows/python-$pyVer-embed-amd64.zip",
    "https://www.python.org/ftp/python/$pyVer/python-$pyVer-embed-amd64.zip"
)
if (-not (TryFetchMany $pythonUrls $zip '下载中')) {
    Say ''
    Say '  [失败] 所有下载源都不通，请连上网络后再双击一次「启动工作台.bat」。' 'Red'
    exit 1
}

Say '  解压中…'
if (Test-Path $PyDir) { Remove-Item $PyDir -Recurse -Force }
try {
    Expand-Archive -Path $zip -DestinationPath $PyDir -Force
} catch {
    Say ('  [失败] 解压失败：' + $_.Exception.Message) 'Red'
    exit 1
}

# embeddable 版默认把 import site 注释掉了，不放开的话 pip 装的包 import 不到。
$pth = Get-ChildItem $PyDir -Filter 'python*._pth' -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($pth) {
    # ⚠️ 换行必须自己拼。实测用 Set-Content / WriteAllLines 传数组时，
    # PowerShell 会把数组用**空格**连成一行，而 ._pth 要求一行一个路径 ——
    # 连成一行后 Python 连 encodings 都找不到，报
    # "Fatal Python error: init_fs_encoding"。别改成数组写法。
    # 第一行必须是同名的 zip（python311.zip），版本号从文件名推出来。
    # 倒数第二行 ..\.. 是项目根目录（相对于 runtime\python）。便携版是 isolated
    # 模式，sys.path 只认这个文件里列的东西 —— 不补这一行，
    # 「python -m backend.server」会报 No module named 'backend'。
    # 用相对路径而不是绝对路径，这样文件夹被挪到哪儿都不会失效。
    $pthText = ($pth.BaseName + '.zip') + "`r`n" +
               '.' + "`r`n" +
               'Lib\site-packages' + "`r`n" +
               '..\..' + "`r`n" +
               'import site' + "`r`n"
    [System.IO.File]::WriteAllText($pth.FullName, $pthText, [System.Text.Encoding]::ASCII)
}

# ---------------------------------------------------------------- 2. pip
Say ''
Say '  [2/3] 准备包管理器'
$gp = Join-Path $Tmp 'get-pip.py'
# 官方那份排第一：实测它自带的新版 pip 能正常跑完；镜像上的版本可能偏旧，
# 放在后面当备用（3.11 环境下旧版也能跑）。
$pipUrls = @(
    'https://bootstrap.pypa.io/get-pip.py',
    'https://mirrors.aliyun.com/pypi/get-pip.py'
)
if (-not (TryFetchMany $pipUrls $gp '下载中')) {
    Say '  [失败] 下载 pip 失败。' 'Red'
    exit 1
}
& $PyExe $gp -i $Index --no-warn-script-location --quiet
if ($LASTEXITCODE -ne 0) {
    Say '  [失败] 安装包管理器（pip）失败。' 'Red'
    exit 1
}

# ---------------------------------------------------------------- 3. 抓取组件
Say ''
Say '  [3/3] 安装抓取组件 Playwright（约 40 MB）'
& $PyExe -m pip install -r (Join-Path $Root 'sync\requirements.txt') `
    -i $Index --no-warn-script-location --quiet
if ($LASTEXITCODE -ne 0) {
    Say '  [失败] 安装 Playwright 失败，请连上网络后重试。' 'Red'
    exit 1
}

Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue

Say ''
Say '  运行环境准备完成。' 'Green'
Say '  接下来会自动打开工作台页面，跟着页面上的向导走就行。'
Say ''
exit 0
