# trade_agents

Python web service served by uvicorn.

## Requirements

Python 3.11 or newer.

## Install

From the project root:

```bash
bash scripts/install.sh
```

The script creates `.venv` and installs the packages in `requirements.txt`. `.venv` stays on the machine and is not committed.

## Run

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Check that the service is up:

```bash
curl http://127.0.0.1:8000/health
```

Expected response: `{"status":"ok"}`.

## Move to another server

1. Clone the repository.
2. Install Python 3.11 or newer.
3. Run `bash scripts/install.sh`.
4. Start uvicorn with the command above.
5. Open `/health` and confirm the response.
