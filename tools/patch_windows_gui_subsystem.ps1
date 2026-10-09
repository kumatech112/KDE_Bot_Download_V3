param(
    [Parameter(Mandatory = $true)]
    [string]$ExecutablePath
)

$ErrorActionPreference = "Stop"

$resolvedExecutablePath = (Resolve-Path -LiteralPath $ExecutablePath).Path
$signature = Get-AuthenticodeSignature -LiteralPath $resolvedExecutablePath
if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::NotSigned) {
    throw "Refusing to modify a signed executable: $resolvedExecutablePath"
}

$stream = [System.IO.File]::Open(
    $resolvedExecutablePath,
    [System.IO.FileMode]::Open,
    [System.IO.FileAccess]::ReadWrite,
    [System.IO.FileShare]::Read
)

try {
    $reader = New-Object System.IO.BinaryReader($stream)
    $writer = New-Object System.IO.BinaryWriter($stream)

    $stream.Position = 0
    $dosSignature = $reader.ReadUInt16()
    if ($dosSignature -ne 0x5A4D) {
        throw "The executable is not a valid Windows PE file: $resolvedExecutablePath"
    }

    $stream.Position = 0x3C
    $peOffset = $reader.ReadInt32()
    $stream.Position = $peOffset
    $peSignature = $reader.ReadUInt32()
    if ($peSignature -ne 0x00004550) {
        throw "The executable has an invalid PE signature: $resolvedExecutablePath"
    }

    $optionalHeaderOffset = $peOffset + 24
    $stream.Position = $optionalHeaderOffset
    $optionalHeaderMagic = $reader.ReadUInt16()
    if ($optionalHeaderMagic -ne 0x010B -and $optionalHeaderMagic -ne 0x020B) {
        throw "The executable has an unsupported PE optional header: $resolvedExecutablePath"
    }

    $subsystemOffset = $optionalHeaderOffset + 68
    $stream.Position = $subsystemOffset
    $currentSubsystem = $reader.ReadUInt16()
    if ($currentSubsystem -ne 2 -and $currentSubsystem -ne 3) {
        throw "The executable has an unexpected PE subsystem value ${currentSubsystem}: $resolvedExecutablePath"
    }

    if ($currentSubsystem -eq 3) {
        $stream.Position = $subsystemOffset
        $writer.Write([UInt16]2)
        $writer.Flush()
        $stream.Flush($true)
    }

    $stream.Position = $subsystemOffset
    $verifiedSubsystem = $reader.ReadUInt16()
    if ($verifiedSubsystem -ne 2) {
        throw "Unable to change the executable to the Windows GUI subsystem: $resolvedExecutablePath"
    }

    Write-Host "Windows PE subsystem: Windows GUI"
    Write-Host $resolvedExecutablePath
}
finally {
    $stream.Dispose()
}
