<#
.SYNOPSIS
Find Album-level folders (Artist\AlbumType\Album) that do not contain audio files.

.DESCRIPTION
This script searches only the "Album" level in a music collection organized as
Artist\AlbumType\Album and prints any Album folders that contain no audio files.

.PARAMETER RootDirectory
The root folder containing artist folders. Default: D:\data\media\music

.PARAMETER MusicExtensions
A list of file wildcard patterns considered audio files. Default includes common extensions.

.EXAMPLE
.
    .\DirectoriesWithoutMusic.ps1 -RootDirectory 'D:\Music' -MusicExtensions '*.mp3','*.m4a'

Returns full paths for Album folders that contain no matching audio files.
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $false)]
    [string]$RootDirectory = "D:\data\media\music",

    [Parameter(Mandatory = $false)]
    [string[]]$MusicExtensions = @("*.mp3", "*.wav", "*.flac", "*.aac", "*.ogg", "*.m4a"),

    [Parameter(Mandatory = $false)]
    [switch]$Delete
)

# Resolve and normalize the root directory
try {
    $root = (Get-Item -LiteralPath $RootDirectory -ErrorAction Stop).FullName
}
catch {
    Write-Error "Root directory '$RootDirectory' not found or inaccessible."
    exit 1
}

# Get all directories under the root (we'll filter to Album-level by relative path parts)
$allDirs = Get-ChildItem -LiteralPath $root -Directory -Recurse -ErrorAction SilentlyContinue

foreach ($dir in $allDirs) {
    # Compute the path relative to the root and split into parts.
    # Expect: Artist\AlbumType\Album  => exactly 3 parts
    $relative = $dir.FullName.Substring($root.Length).TrimStart('\', '/')
    if ($relative -eq '') { continue } # skip the root itself

    $parts = $relative -split '[\\/]'
    if ($parts.Count -ne 3) { continue } # not an Album-level directory

    # Check for any music files directly inside the Album folder (non-recursive)
    $containsMusic = $false
    foreach ($ext in $MusicExtensions) {
        # Use Test-Path/Path so wildcards are expanded. -LiteralPath would treat the wildcard literally
        $pattern = Join-Path $dir.FullName $ext
        if (Test-Path -Path $pattern) {
            $containsMusic = $true
            break
        }
    }

    if (-not $containsMusic) {
        # Report the album folder lacking audio files
        Write-Output $dir.FullName

        if ($Delete) {
            # Use ShouldProcess so -WhatIf and -Confirm work
            if ($PSCmdlet.ShouldProcess($dir.FullName, 'Remove album directory that contains no audio files')) {
                try {
                    Remove-Item -LiteralPath $dir.FullName -Recurse -Force -ErrorAction Stop
                    Write-Output "Removed: $($dir.FullName)"
                }
                catch {
                    Write-Warning "Failed to remove $($dir.FullName): $($_.Exception.Message)"
                }
            }
        }
    }
}