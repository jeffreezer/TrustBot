FROM python:3.12-slim

WORKDIR /app

# System deps kept minimal; psycopg[binary] needs no build tools.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY entrypoint.sh ./
COPY app ./app

RUN chmod +x entrypoint.sh

EXPOSE 8000
# Migrate + seed (idempotent) + serve. See entrypoint.sh.
CMD ["./entrypoint.sh"]
