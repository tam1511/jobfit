# JobFit

Chấm và tối ưu CV theo mô tả công việc.

## Run it

```
scripts/start-mac.sh      # or start-linux.sh / start-windows.ps1
```

Then open http://localhost:8000. Stop with the matching `stop-*` script.

Requires Docker.

## Develop it

Backend:

```
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
backend/.venv/bin/uvicorn app.main:app --app-dir backend --reload
```

Frontend:

```
cd frontend
npm install
npm run build   # writes to frontend/out; FastAPI serves this
```

Tests:

```
backend/.venv/bin/pytest backend/tests
```
