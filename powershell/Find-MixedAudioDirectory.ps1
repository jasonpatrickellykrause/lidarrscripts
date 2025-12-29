<#
.SYNOPSIS
Find directories containing mixed audio file formats.

.DESCRIPTION
Searches a music collection for album directories that contain multiple audio file types
(e.g., FLAC + MP3). This is useful for identifying albums that may need upgrading or 
format consolidation in Lidarr. The script reports directories meeting the minimum 
threshold of different audio file types and provides an optional CSV export.

.PARAMETER Path
The root folder to search for music directories. Default: current directory.

.PARAMETER MinTypes
The minimum number of different audio file types required to report a directory. Default: 2.

.EXAMPLE
.\Find-MixedAudioDirectory.ps1 -Path "D:\Music" -MinTypes 2

Searches D:\Music for directories containing 2 or more different audio file types.

.EXAMPLE
.\Find-MixedAudioDirectory.ps1 -Path "C:\Music\Artist" -MinTypes 3

Searches C:\Music\Artist for directories with 3 or more different audio file types.
#>

param(
    [string]$Path = ".",
    [int]$MinTypes = 2
)

# Define common audio file extensions
$audioExtensions = @('.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.wma', '.opus', '.aiff', '.ape')

Write-Host "Searching for directories with at least $MinTypes different audio file types..." -ForegroundColor Cyan
Write-Host "Path: $Path`n" -ForegroundColor Cyan

# Get all directories
$directories = Get-ChildItem -Path $Path -Directory -Recurse -ErrorAction SilentlyContinue

$results = @()

foreach ($dir in $directories) {
    # Get audio files in current directory (non-recursive)
    $audioFiles = Get-ChildItem -Path $dir.FullName -File -ErrorAction SilentlyContinue | 
    Where-Object { $audioExtensions -contains $_.Extension.ToLower() }
    
    if ($audioFiles) {
        # Get unique file types in this directory
        $uniqueTypes = $audioFiles | Select-Object -ExpandProperty Extension | 
        ForEach-Object { $_.ToLower() } | Select-Object -Unique
        
        $typeCount = ($uniqueTypes | Measure-Object).Count
        
        # Only include directories with minimum required types
        if ($typeCount -ge $MinTypes) {
            $results += [PSCustomObject]@{
                Directory = $dir.FullName
                TypeCount = $typeCount
                FileTypes = ($uniqueTypes -join ', ')
                FileCount = ($audioFiles | Measure-Object).Count
            }
        }
    }
}

# Display results sorted by type count (descending)
if ($results.Count -gt 0) {
    Write-Host "Found $($results.Count) directories with multiple audio types:`n" -ForegroundColor Green
    $results | Sort-Object -Property TypeCount -Descending | Format-Table -AutoSize
    
    # Export option
    $export = Read-Host "`nExport results to CSV? (Y/N)"
    if ($export -eq 'Y' -or $export -eq 'y') {
        $csvPath = Join-Path $PWD "AudioDirectories_$(Get-Date -Format 'yyyyMMdd_HHmmss').csv"
        $results | Export-Csv -Path $csvPath -NoTypeInformation
        Write-Host "Results exported to: $csvPath" -ForegroundColor Green
    }
}
else {
    Write-Host "No directories found with $MinTypes or more audio file types." -ForegroundColor Yellow
}