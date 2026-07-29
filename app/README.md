# 13f-data.com application

Local read-only web application for the canonical Form 13F analytical database.

## Run

From the project root:

```bash
./app/start.sh
```

The script installs missing local dependencies, builds the React application,
and starts the API and site at <http://127.0.0.1:8000>.

For frontend development with hot reload, run the API in one terminal and Vite
in another:

```bash
source .venv/bin/activate
uvicorn app.backend.main:app --reload

cd app/frontend
npm run dev
```

The Vite development site is available at <http://127.0.0.1:5173> and proxies
`/api` requests to the Python API.

## Database

The backend opens `form13f.sqlite3` in SQLite read-only mode. Override its path
when necessary:

```bash
FORM13F_DATABASE=/absolute/path/to/form13f.sqlite3 ./app/start.sh
```

Interactive API documentation is available at <http://127.0.0.1:8000/docs>.
Every SQL statement behind the application is defined in
`app/backend/queries.py`.
