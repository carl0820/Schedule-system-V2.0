# Create GitHub Release Script
# Creates a GitHub release for the current tag

param(
    [string]$Tag = "",
    [string]$Token = ""
)

# Get the latest tag if not specified
if (-not $Tag) {
    $Tag = git describe --tags --abbrev=0
    Write-Host "Using latest tag: $Tag" -ForegroundColor Cyan
}

# Check if tag exists
$tagExists = git tag -l $Tag
if (-not $tagExists) {
    Write-Host "[ERROR] Tag $Tag does not exist" -ForegroundColor Red
    Write-Host "Available tags:" -ForegroundColor Yellow
    git tag -l
    exit 1
}

# Get release notes
$releaseNotes = ""
if (Test-Path "RELEASE_NOTES_$Tag.md") {
    $releaseNotes = Get-Content "RELEASE_NOTES_$Tag.md" -Raw
} else {
    Write-Host "[WARN] Release notes file not found: RELEASE_NOTES_$Tag.md" -ForegroundColor Yellow
    $releaseNotes = "Release $Tag - See commit history for details"
}

# Get GitHub token
if (-not $Token) {
    $Token = $env:GITHUB_TOKEN
}

if (-not $Token) {
    Write-Host "[ERROR] GitHub token not found" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please provide a GitHub Personal Access Token:" -ForegroundColor Yellow
    Write-Host "  1. Go to: https://github.com/settings/tokens" -ForegroundColor Cyan
    Write-Host "  2. Generate a new token with 'repo' scope" -ForegroundColor Cyan
    Write-Host "  3. Run: `$env:GITHUB_TOKEN='your-token'; .\create_release.ps1 -Tag $Tag" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Or set it as environment variable:" -ForegroundColor Yellow
    Write-Host "  `$env:GITHUB_TOKEN='your-token'" -ForegroundColor Cyan
    exit 1
}

# Create release via GitHub API
$repo = "carl0820/schedule-system-based-on-REST"
$apiUrl = "https://api.github.com/repos/$repo/releases"

$releaseData = @{
    tag_name = $Tag
    name = "Release $Tag"
    body = $releaseNotes
    draft = $false
    prerelease = $false
} | ConvertTo-Json

Write-Host "Creating release for tag: $Tag" -ForegroundColor Cyan
Write-Host "Repository: $repo" -ForegroundColor Cyan
Write-Host ""

try {
    $headers = @{
        "Authorization" = "token $Token"
        "Accept" = "application/vnd.github.v3+json"
    }
    
    $response = Invoke-RestMethod -Uri $apiUrl -Method Post -Headers $headers -Body $releaseData -ContentType "application/json"
    
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Release created successfully!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Tag: $Tag" -ForegroundColor Cyan
    Write-Host "  Release URL: $($response.html_url)" -ForegroundColor Cyan
    Write-Host "  Release ID: $($response.id)" -ForegroundColor Cyan
    Write-Host ""
    
    # Open release page in browser
    Start-Process $response.html_url
    
} catch {
    Write-Host "[ERROR] Failed to create release" -ForegroundColor Red
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.ErrorDetails.Message) {
        Write-Host "Details: $($_.ErrorDetails.Message)" -ForegroundColor Yellow
    }
    exit 1
}

