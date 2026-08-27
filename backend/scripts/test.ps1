# PowerShell test runner for the EngageOS backend test suite.
#
# Usage:
#   .\scripts\test.ps1 unit      # fast unit tier (no Docker)
#   .\scripts\test.ps1 int       # integration tier (boots compose)
#   .\scripts\test.ps1 e2e       # E2E tier (boots compose, Celery eager)
#   .\scripts\test.ps1 all       # unit + integration + e2e (NOT live)
#   .\scripts\test.ps1 live      # live API tier (requires RUN_LIVE_TESTS=1)
#   .\scripts\test.ps1 cov       # coverage, HTML report to backend/htmlcov/
#   .\scripts\test.ps1 up        # just bring the compose stack up
#   .\scripts\test.ps1 down      # tear the compose stack down

param([Parameter(Mandatory=$false)][string]$Tier = "unit")

$ErrorActionPreference = "Stop"
Set-Location -Path "$PSScriptRoot\.."

function Start-TestStack {
    Write-Host "Bringing up docker-compose.test.yml..." -ForegroundColor Cyan
    docker compose -f docker-compose.test.yml up -d --wait
    if ($LASTEXITCODE -ne 0) { throw "Docker compose failed to start" }
}

function Stop-TestStack {
    Write-Host "Tearing down docker-compose.test.yml..." -ForegroundColor Cyan
    docker compose -f docker-compose.test.yml down -v
}

function Set-TestEnv {
    $env:DATABASE_URL = "postgresql+asyncpg://engageos:engageos@localhost:55432/engageos_test"
    $env:REDIS_URL    = "redis://localhost:56379/0"
    $env:CELERY_BROKER_URL = $env:REDIS_URL
    $env:CELERY_RESULT_BACKEND = $env:REDIS_URL
    $env:ENV = "test"
}

switch ($Tier) {
    "unit" {
        Set-TestEnv
        pytest -m "not integration and not e2e and not live" -v
    }
    "int" {
        Start-TestStack
        Set-TestEnv
        pytest -m integration -v
    }
    "e2e" {
        Start-TestStack
        Set-TestEnv
        pytest -m e2e -v
    }
    "all" {
        Start-TestStack
        Set-TestEnv
        pytest -m "not live" -v
    }
    "live" {
        if ($env:RUN_LIVE_TESTS -ne "1") {
            Write-Host "Set RUN_LIVE_TESTS=1 first. Live tests send real WhatsApp messages and incur costs." -ForegroundColor Yellow
            exit 1
        }
        Set-TestEnv
        pytest -m live -v
    }
    "cov" {
        Start-TestStack
        Set-TestEnv
        pytest --cov=app --cov-report=term-missing --cov-report=html --cov-fail-under=85 -m "not live"
    }
    "up"   { Start-TestStack }
    "down" { Stop-TestStack }
    default {
        Write-Host "Unknown tier: $Tier. Use: unit | int | e2e | all | live | cov | up | down" -ForegroundColor Red
        exit 1
    }
}
