# RAKETEX

RAKETEX is the Flask version of the site. There is no static `index.html` version in this repo anymore.

## Local run

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

Admin login defaults:

```text
username: admin
password: raketex123
```

## Persistent data

Posts are stored in SQLite:

```text
instance/raketex.db
```

Uploaded images are stored in:

```text
instance/uploads/
```

For production hosting, use a service with persistent disk storage and set:

```text
RAKETEX_DATA_DIR=/path/to/persistent/data
```

Vercel can run Flask, but its serverless filesystem is not a good place for a persistent SQLite database or uploads. Use hosting with persistent disk, or replace SQLite/uploads with a hosted database and object storage.
