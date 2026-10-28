# UI Automation lookups for tools/drag_driver.py. A developer diagnostic, not shipped.
#
# Reads one JSON command per line on stdin and writes one JSON answer per line on stdout.
# It is read-only: it finds windows and items and checks points, but never clicks or types.
# Commands send ASCII only. Answers carry numbers and control-type names, never file or folder
# names, so a non-ASCII path elsewhere on the machine can't garble the pipe.
#
#   {"cmd": "ping"}
#   {"cmd": "find_window", "path": "C:\\...\\morphwheel-dragtest"}  -> hwnds showing that folder
#   {"cmd": "locate", "hwnd": 123, "name": "mw-test-a.png"}         -> item rect and a press point
#   {"cmd": "check", "hwnd": 123, "name": "mw-test-a.png", "x": 1, "y": 2}  -> is (x, y) on the item?
#   {"cmd": "inspect", ...same as check...}  -> what is under (x, y) (diagnostic)
#   {"cmd": "list_rect", "hwnd": 123}  -> the items view's rectangle

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class MwDpi {
    [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr value);
    [DllImport("user32.dll")] public static extern uint GetDpiForSystem();
}
"@
# Physical pixels, like the driver. powershell.exe may already be DPI aware; the driver also
# insists on 96 DPI, where both agree anyway.
$null = [MwDpi]::SetProcessDpiAwarenessContext([IntPtr](-4))

$AE = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]
$CT = [System.Windows.Automation.ControlType]
$Walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker

function Get-Rect($r) {
    @{ left = [int]$r.Left; top = [int]$r.Top; right = [int]$r.Right; bottom = [int]$r.Bottom }
}

function Find-Item([int64]$hwnd, [string]$name) {
    $root = $AE::FromHandle([IntPtr]$hwnd)
    $stem = [IO.Path]::GetFileNameWithoutExtension($name)  # file extensions may be hidden
    $isItem = New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $CT::ListItem)
    foreach ($el in $root.FindAll($TS::Descendants, $isItem)) {
        $n = $el.Current.Name
        if ($n -ceq $name -or $n -ceq $stem) { return $el }
    }
    return $null
}

function Test-Hit([double]$x, [double]$y, $item) {
    # The element under (x, y) must be the item or inside it, and never its checkbox.
    $hit = $AE::FromPoint((New-Object System.Windows.Point($x, $y)))
    $type = $hit.Current.ControlType.ProgrammaticName
    if ($type -eq 'ControlType.CheckBox') { return @{ ok = $false; hit = $type } }
    $el = $hit
    for ($i = 0; $i -lt 8 -and $null -ne $el; $i++) {
        if ([System.Windows.Automation.Automation]::Compare($el, $item)) { return @{ ok = $true; hit = $type } }
        $el = $Walker.GetParent($el)
    }
    return @{ ok = $false; hit = $type }
}

function Invoke-Locate($cmd) {
    $item = Find-Item $cmd.hwnd $cmd.name
    if ($null -eq $item) { return @{ ok = $false; error = 'item not found' } }
    $rect = $item.Current.BoundingRectangle
    if ($rect.IsEmpty -or $item.Current.IsOffscreen) { return @{ ok = $false; error = 'item not on screen' } }
    $candidates = @()
    $isLabel = New-Object System.Windows.Automation.PropertyCondition($AE::AutomationIdProperty, 'System.ItemNameDisplay')
    $label = $item.FindFirst($TS::Descendants, $isLabel)
    if ($null -ne $label -and -not $label.Current.BoundingRectangle.IsEmpty) {
        $l = $label.Current.BoundingRectangle
        # The centre of the label: the text is centred there. The label element spans the whole
        # tile, and a press on its padding starts a rubber-band selection, not a file drag.
        $candidates += , @((($l.Left + $l.Right) / 2), (($l.Top + $l.Bottom) / 2))
    }
    $candidates += , @((($rect.Left + $rect.Right) / 2), (($rect.Top + $rect.Bottom) / 2))
    foreach ($c in $candidates) {
        $x = [int][Math]::Round($c[0]); $y = [int][Math]::Round($c[1])
        $t = Test-Hit $x $y $item
        if ($t.ok) { return @{ ok = $true; x = $x; y = $y; hit = $t.hit; item = (Get-Rect $rect) } }
    }
    return @{ ok = $false; error = 'no press point passed the hit test'; item = (Get-Rect $rect) }
}

function Invoke-Inspect($cmd) {
    # Diagnostic: what is under (x, y), and how it relates to the item.
    $item = Find-Item $cmd.hwnd $cmd.name
    $hit = $AE::FromPoint((New-Object System.Windows.Point($cmd.x, $cmd.y)))
    $chain = @()
    $el = $hit
    for ($i = 0; $i -lt 8 -and $null -ne $el; $i++) {
        $chain += @{
            type = $el.Current.ControlType.ProgrammaticName
            name_len = $el.Current.Name.Length
            name_matches = ($null -ne $item -and ($el.Current.Name -ceq $item.Current.Name))
            rect = (Get-Rect $el.Current.BoundingRectangle)
            same = ($null -ne $item -and [System.Windows.Automation.Automation]::Compare($el, $item))
            runtime_id = ($el.GetRuntimeId() -join '.')
        }
        $el = $Walker.GetParent($el)
    }
    $info = @{ ok = $true; chain = $chain }
    if ($null -ne $item) {
        $info.item = @{ rect = (Get-Rect $item.Current.BoundingRectangle); runtime_id = ($item.GetRuntimeId() -join '.') }
    }
    return $info
}

function Invoke-Check($cmd) {
    $item = Find-Item $cmd.hwnd $cmd.name
    if ($null -eq $item) { return @{ ok = $false; error = 'item not found' } }
    return Test-Hit $cmd.x $cmd.y $item
}

function Invoke-ListRect($cmd) {
    # The items view ("Items View" list) of an Explorer window: where a release can't move a file.
    $root = $AE::FromHandle([IntPtr]$cmd.hwnd)
    $isList = New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $CT::List)
    foreach ($el in $root.FindAll($TS::Descendants, $isList)) {
        if ($el.Current.Name -ceq 'Items View') { return @{ ok = $true; rect = (Get-Rect $el.Current.BoundingRectangle) } }
    }
    return @{ ok = $false; error = 'no Items View list' }
}

function Invoke-FindWindow($cmd) {
    $shell = New-Object -ComObject Shell.Application
    $hwnds = @()
    foreach ($w in $shell.Windows()) {
        try { $p = $w.Document.Folder.Self.Path } catch { $p = $null }
        if ($null -ne $p -and $p -eq $cmd.path) { $hwnds += [int64]$w.HWND }
    }
    return @{ ok = $true; hwnds = $hwnds; system_dpi = [MwDpi]::GetDpiForSystem() }
}

while ($null -ne ($line = [Console]::In.ReadLine())) {
    try {
        $cmd = ConvertFrom-Json $line
        $answer = switch ($cmd.cmd) {
            'ping' { @{ ok = $true; system_dpi = [MwDpi]::GetDpiForSystem() } }
            'find_window' { Invoke-FindWindow $cmd }
            'locate' { Invoke-Locate $cmd }
            'check' { Invoke-Check $cmd }
            'inspect' { Invoke-Inspect $cmd }
            'list_rect' { Invoke-ListRect $cmd }
            default { @{ ok = $false; error = "unknown command" } }
        }
    } catch {
        $answer = @{ ok = $false; error = ($_.Exception.Message -replace '[^\x20-\x7E]', '?') }
    }
    [Console]::Out.WriteLine((ConvertTo-Json $answer -Compress -Depth 5))
    [Console]::Out.Flush()
}
