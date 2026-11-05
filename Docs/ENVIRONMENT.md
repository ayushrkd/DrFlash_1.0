# JARVIS — Development Environment Report

> Generated: 2026-11-06 | Machine: Personal workstation

## Operating System

| Property | Value |
|---|---|
| OS | Microsoft Windows 11 Home Single Language |
| Version | 10.0.26200 Build 26200 |
| Architecture | x64-based PC |

## Hardware

| Component | Details |
|---|---|
| CPU | Intel Core Ultra 9 275HX — 24 cores / 24 threads |
| RAM | 32 GB |
| GPU | NVIDIA GeForce RTX 5070 Laptop GPU — 8,151 MiB VRAM |
| GPU Compute | Capability 12.0 (Blackwell) |
| GPU Driver | 577.13 |

## Development Runtimes

| Runtime | Version | Path / Notes |
|---|---|---|
| Python | 3.14.0 | `C:\Python314\python.exe` |
| Node.js | 22.20.0 | — |
| npm | 11.9.0 | — |
| pnpm | 12.15.0 | — |
| .NET SDK | 10.0.301 | `C:\Program Files\dotnet\sdk` |
| Git | 2.51.0.windows.2 | — |
| pip | 25.2 | — |
| uv | 0.13.7 | Installed via pip (user) |
| Ollama | 0.40.13 | Running locally |

## Local Models (Ollama)

| Model | Size | Notes |
|---|---|---|
| qwen2.5:7b-instruct-q4_K_M | 4.7 GB | Good for local dialog/intent |
| llama3.2:3b | 2.0 GB | Fast intent/routing/classification |
| qwen3.6:latest | 23 GB | Heavy; may not fit entirely in 8GB VRAM |
| gpt-oss:20b | 13 GB | Large; partial offload needed |
| bge-m3:latest | 1.2 GB | Multilingual embeddings |
| nomic-embed-text:latest | 274 MB | Text embeddings |

## Capacity Assessment

- **8 GB VRAM** comfortably runs quantized models up to ~7B parameters with context
- qwen2.5:7b-instruct is the best balance of quality/speed for local dialog
- llama3.2:3b is ideal for fast intent classification and routing
- Embedding models (bge-m3, nomic-embed-text) are lightweight and can coexist
- 32 GB RAM provides ample headroom for CPU offload and application memory
- 24-core CPU handles parallel processing well (build, inference fallback, workers)

## Constraints

- Python 3.14 is very new; some packages may need compatibility verification
- 8 GB VRAM limits concurrent model loading; only one large model at a time
- No `uv` was pre-installed (now installed); using pip as fallback
- No AWS credentials verified yet; Bedrock access to be validated when needed
- No secrets, credentials, or personal data collected in this report
