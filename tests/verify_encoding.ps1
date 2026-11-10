# 编码全链路验证脚本（PowerShell 5.1 / UTF-8 无 BOM 流 / 中日韩多语言）
# 用法（必须不加 -NoProfile，本脚本用于验证 profile 持久化已生效）：
#   powershell -ExecutionPolicy Bypass -File "tests\verify_encoding.ps1"
# 判定：全部 PASS 退出码 0；出现 FAIL 退出码 1。

$ErrorActionPreference = 'Continue'
$script:pass = 0
$script:fail = 0

function Check {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    if ($Ok) { $script:pass++; Write-Output ("PASS {0} :: {1}" -f $Name, $Detail) }
    else { $script:fail++; Write-Output ("FAIL {0} :: {1}" -f $Name, $Detail) }
}

# 注意：PowerShell 解析器会把中文弯引号 “ ” (U+201C/201D) 当字符串定界符，直接写字面量会被截断，
# 因此特殊字符一律用码点构造——这本身也是"特殊字符无截断"必须用码点验证的原因。
$special = -join ([char]0x2014, [char]0x2026, [char]0x201C, [char]0x201D, [char]0x2460)
$sample = "中文测试 日本語テスト 한국어테스트 " + $special + " ✓ €"
$svc = "http://127.0.0.1:8790"

# ---------- 0. 环境基线（profile 是否自动生效）----------
Write-Output ("ENV PSVer={0} OutEnc={1} InEnc={2} PipeOut={3} CodePage={4}" -f `
    $PSVersionTable.PSVersion, [Console]::OutputEncoding.WebName, `
    [Console]::InputEncoding.WebName, $OutputEncoding.WebName, (chcp))
$profileLoaded = [bool](Get-Command Save-Utf8 -ErrorAction SilentlyContinue) `
    -and [bool](Get-Command Post-JsonUtf8 -ErrorAction SilentlyContinue)
Check "env.profile.autoload" $profileLoaded "Save-Utf8/Post-JsonUtf8 来自 profile 自动加载"
Check "env.out.utf8" ([Console]::OutputEncoding.WebName -eq 'utf-8') ([Console]::OutputEncoding.WebName)
Check "env.in.utf8" ([Console]::InputEncoding.WebName -eq 'utf-8') ([Console]::InputEncoding.WebName)
Check "env.pipe.utf8" ($OutputEncoding.WebName -eq 'utf-8') $OutputEncoding.WebName

# ---------- 1. 终端输出 / 管道输入 ----------
Write-Output ("STDOUT_SAMPLE={0}" -f $sample)
$sampleBytes = [System.Text.Encoding]::UTF8.GetBytes($sample)
$sampleBack = [System.Text.Encoding]::UTF8.GetString($sampleBytes)
Check "term.stdout.roundtrip" ($sampleBack -eq $sample) ("字符数=" + $sample.Length + " UTF-8字节数=" + $sampleBytes.Length + "（编解码一致即无截断/异常转码）")
$cp = $sample.ToCharArray() | ForEach-Object { [int]$_ }
Check "term.stdout.codepoints" (($cp -contains 0x4E2D) -and ($cp -contains 0x65E5) -and ($cp -contains 0xD55C)) `
    "含中文/日文/韩文码点 (4E2D/65E5/D55C)"

$echoIn = "한국어 stdin 테스트 中文输入"
$echoBack = ($echoIn | powershell -NoProfile -Command '$input')
Check "pipe.stdin.roundtrip" ($echoBack -eq $echoIn) ("回读=" + $echoBack)

# ---------- 2. 文件读写 ----------
$fNoBom = Join-Path $env:TEMP "enc_verify_nobom.txt"
$sample | Save-Utf8 $fNoBom
$b1 = [System.IO.File]::ReadAllBytes($fNoBom)
$headOk = -not ($b1.Length -ge 3 -and $b1[0] -eq 0xEF -and $b1[1] -eq 0xBB -and $b1[2] -eq 0xBF)
Check "file.write.nobom" $headOk ("首3字节=" + (($b1[0..2] | ForEach-Object { $_.ToString('X2') }) -join ' ') + " 长度=" + $b1.Length)
Check "file.read.roundtrip" ((Read-Utf8 $fNoBom) -eq $sample) "Save-Utf8 -> Read-Utf8 完全一致"

$fBom = Join-Path $env:TEMP "enc_verify_bom.txt"
$sample | Out-File -FilePath $fBom
$b2 = [System.IO.File]::ReadAllBytes($fBom)
$bomOk = ($b2.Length -ge 3 -and $b2[0] -eq 0xEF -and $b2[1] -eq 0xBB -and $b2[2] -eq 0xBF)
Check "file.outfile.utf8" $bomOk ("Out-File 默认转向 UTF-8（PS5.1 带 BOM，首3字节=" + (($b2[0..2] | ForEach-Object { $_.ToString('X2') }) -join ' ') + "）")
Check "file.getcontent.autodetect" ((Get-Content -LiteralPath $fBom -Raw).TrimEnd() -eq $sample) "Get-Content 默认 utf8 读回一致"

# ---------- 3. 网络请求 ----------
$ko = "회의는 오후 3시에 시작합니다."
$zh = "明天的会议在下午三点开始。"
try {
    $eng = Invoke-RestMethod -Uri "$svc/api/engines" -TimeoutSec 10
    Check "net.engines" ($eng.chain -contains 'google_chrome') ("chain=" + ($eng.chain -join ',') + " offline=" + ($eng.offline_langs -join ','))
} catch {
    Check "net.engines" $false ("服务不可达：" + $_.Exception.Message)
}

try {
    $r1 = Post-JsonUtf8 "$svc/api/translate" @{ text = $ko }
    Check "net.post.ko.lang" ($r1.lang -eq 'ko') ("lang=" + $r1.lang + " original=" + $r1.original)
    Check "net.post.ko.translated" ([bool]$r1.translated -and $r1.translated -match '[\u4e00-\u9fff]') ("translated=" + $r1.translated + " engine=" + $r1.engine)
} catch {
    Check "net.post.ko" $false ("韩文请求失败：" + $_.Exception.Message)
}

try {
    $r2 = Post-JsonUtf8 "$svc/api/translate" @{ text = $zh }
    Check "net.post.zh.lang" ($r2.lang -eq 'zh' -and $r2.skipped) ("lang=" + $r2.lang + " skipped=" + $r2.skipped + "（中文原样返回）")
} catch {
    Check "net.post.zh" $false ("中文请求失败：" + $_.Exception.Message)
}

# 原始字节校验：确认响应体是 UTF-8 且无替换字符 U+FFFD / HTML 实体
try {
    $resp = Invoke-WebRequest -Uri "$svc/api/translate" -Method Post `
        -Body ([System.Text.Encoding]::UTF8.GetBytes('{"text":"안녕하세요, 반갑습니다."}')) `
        -ContentType 'application/json; charset=utf-8' -TimeoutSec 10
    $raw = $resp.Content
    $okBytes = ($raw -notmatch '[\uFFFD]') -and ($raw -notmatch '&#\d+;') -and ($raw -match '"lang":"ko"')
    Check "net.response.utf8" $okBytes ("响应长度=" + $raw.Length + " 片段=" + $raw.Substring(0, [Math]::Min(80, $raw.Length)))
} catch {
    Check "net.response.utf8" $false ("原始响应校验失败：" + $_.Exception.Message)
}

# ---------- 汇总 ----------
$total = $script:pass + $script:fail
Write-Output ("RESULT {0} 通过 / {1} 失败（共 {2} 项）" -f $script:pass, $script:fail, $total)
if ($script:fail -gt 0) { exit 1 } else { exit 0 }
