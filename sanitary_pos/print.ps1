param([string]$Payload)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
$job = Get-Content -LiteralPath $Payload -Raw -Encoding UTF8 | ConvertFrom-Json
$document = New-Object System.Drawing.Printing.PrintDocument
$document.DocumentName = 'Sanitary Shop'
$document.DefaultPageSettings.Margins = New-Object System.Drawing.Printing.Margins(4,4,4,4)
$dialog = New-Object System.Windows.Forms.PrintDialog
$dialog.Document = $document
$dialog.UseEXDialog = $true
$document.PrinterSettings.Copies = [int16]$job.copies
if ($job.printer) {
    $document.PrinterSettings.PrinterName = [string]$job.printer
} else {
    if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
}
$font = New-Object System.Drawing.Font('Consolas',9)
$script:remaining = [string]$job.text
$script:firstPage = $true
$document.add_PrintPage({
    param($sender, $eventArgs)
    $bounds = $eventArgs.MarginBounds
    $top = [single]$bounds.Top
    if ($script:firstPage -and $job.logo) {
        $logoStream = New-Object System.IO.MemoryStream(,[Convert]::FromBase64String($job.logo))
        $logo = [System.Drawing.Image]::FromStream($logoStream)
        try {
            $ratio = [Math]::Min(100.0 / $logo.Width, 50.0 / $logo.Height)
            $logoWidth = [single]($logo.Width * $ratio)
            $logoHeight = [single]($logo.Height * $ratio)
            $eventArgs.Graphics.DrawImage($logo, [single]($bounds.Left+($bounds.Width-$logoWidth)/2), $top, $logoWidth, $logoHeight)
            $top += $logoHeight + 8
        } finally { $logo.Dispose(); $logoStream.Dispose() }
    }
    if ($script:firstPage -and $null -ne $job.matrix) {
        $count = $job.matrix.Count
        $qrSize = [single](20.0 / 25.4 * 100)
        if ($bounds.Width -lt $qrSize -or $bounds.Height -lt ($qrSize+20)) { throw 'Choose paper large enough for a 20 mm QR and its code.' }
        $left = [single]($bounds.Left + ($bounds.Width-$qrSize)/2)
        $module = [single]($qrSize / $count)
        for ($row = 0; $row -lt $count; $row++) {
            for ($col = 0; $col -lt $count; $col++) {
                if ($job.matrix[$row][$col]) {
                    $eventArgs.Graphics.FillRectangle([System.Drawing.Brushes]::Black, [single]($left+$col*$module), [single]($top+$row*$module), $module, $module)
                }
            }
        }
        $top += $qrSize + 2
        $codeFont = New-Object System.Drawing.Font('Arial',8)
        $codeFormat = New-Object System.Drawing.StringFormat
        $codeFormat.Alignment = [System.Drawing.StringAlignment]::Center
        $codeWidth = [Math]::Min($bounds.Width, 110)
        $measured = $eventArgs.Graphics.MeasureString([string]$job.text, $codeFont).Width
        if ($measured -gt $codeWidth) {
            $codeFont.Dispose()
            $codeFont = New-Object System.Drawing.Font('Arial', [single](8*$codeWidth/$measured))
        }
        $codeArea = New-Object System.Drawing.RectangleF(($bounds.Left+($bounds.Width-$codeWidth)/2),$top,$codeWidth,20)
        $eventArgs.Graphics.DrawString([string]$job.text,$codeFont,[System.Drawing.Brushes]::Black,$codeArea,$codeFormat)
        $codeFont.Dispose(); $codeFormat.Dispose()
        $eventArgs.HasMorePages = $false
        $script:firstPage = $false
        return
    }
    $area = New-Object System.Drawing.RectangleF($bounds.Left,$top,$bounds.Width,($bounds.Bottom-$top))
    if ($area.Height -lt 20) { throw 'Paper is too short. Choose a larger label or receipt paper.' }
    $chars = 0
    $lines = 0
    $format = New-Object System.Drawing.StringFormat
    $format.FormatFlags = [System.Drawing.StringFormatFlags]::LineLimit
    $null = $eventArgs.Graphics.MeasureString($script:remaining,$font,$area.Size,$format,[ref]$chars,[ref]$lines)
    if ($chars -eq 0) { throw 'Paper is too small for the text.' }
    $eventArgs.Graphics.DrawString($script:remaining.Substring(0,$chars),$font,[System.Drawing.Brushes]::Black,$area,$format)
    $script:remaining = $script:remaining.Substring($chars)
    $eventArgs.HasMorePages = $script:remaining.Length -gt 0
    $script:firstPage = $false
    $format.Dispose()
})
try { $document.Print() } finally { $font.Dispose(); $dialog.Dispose(); $document.Dispose() }
