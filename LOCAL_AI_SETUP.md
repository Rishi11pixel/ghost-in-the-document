# Local AI setup (GLiNER + Ollama)

This setup is optional for the app, but required to demonstrate both open-source AI layers. All inference should happen on the same computer. Do not configure a remote Ollama host.

## 1. Install the optional NER dependency

From the project root in PowerShell:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
```

If PyTorch is already installed in this virtual environment, pip may keep it. If installation fails, use the PyTorch CPU installation instructions for your Python version, then rerun the command.

## 2. Download GLiNER once while online

```powershell
.venv\Scripts\python.exe scripts\download_gliner.py
$env:GHOST_GLINER_MODEL_PATH = (Resolve-Path ".models\gliner-small-v2.1").Path
```

The model is stored under `.models\gliner-small-v2.1`. Do not delete this directory before an offline demo. Model downloads happen only in this setup script; the app itself expects a local directory and does not fetch a GLiNER model during scanning.

## 3. Check Ollama

Check installed models:

```powershell
ollama list
```

The default model is `qwen2.5:3b`. If it is missing, while online run:

```powershell
ollama pull qwen2.5:3b
```

To compare the other model if available:

```powershell
ollama pull llama3.2:3b
```

Ollama's local service is usually already running on Windows. If it is not running, start `ollama serve` in a separate terminal. Configure the selected local model in the project terminal:

```powershell
$env:GHOST_OLLAMA_MODEL = "qwen2.5:3b"
```

The app refuses Ollama endpoints that do not use a loopback host (`127.0.0.1`, `localhost`, or `::1`).

## 4. Run offline

After both models are downloaded and cached, disconnect from the internet. In the same PowerShell session where the environment variables are set, run:

```powershell
.venv\Scripts\python.exe -m app.ui
```

Leave **Use local AI assist** checked. If the UI reports that a model is skipped or unavailable, the app falls back to regex and hidden scanning; do not claim the AI layer ran until the warning is resolved. Candidate findings from AI are suggestions and must be reviewed like all other findings.

## 5. Evaluate the layers

Baseline rules/hidden scanner, deterministic and quick:

```powershell
.venv\Scripts\python.exe -m app.evaluate
```

AI-enabled evaluation using Qwen:

```powershell
.venv\Scripts\python.exe -m app.evaluate --with-ai --model qwen2.5:3b
```

AI-enabled evaluation using Llama:

```powershell
.venv\Scripts\python.exe -m app.evaluate --with-ai --model llama3.2:3b
```

Each AI run writes a model-specific JSON file, for example `evaluation-results-ai-qwen2_5_3b.json`. Compare precision, recall, false positives, missed items, runtime, layer contributions, and warnings. If the warnings show an AI layer was skipped, label that run as incomplete rather than presenting it as an AI result.

## Important limits

- GLiNER and Ollama results are not guaranteed to detect every sensitive detail.
- The Ollama LLM only accepts returned spans that appear verbatim in the source chunk; this reduces hallucinated targets but does not guarantee correct classification.
- Exact-string evaluation on ten synthetic fixtures is a small benchmark, not a privacy certification.
- Use synthetic documents for testing and demos. Keep generated JSON reports private because they may contain the matched text.
