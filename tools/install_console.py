"""
Add the operations console to the stack. Run from the repo root:
    python3 tools/install_console.py
Appends a `console` service to docker-compose.yml. Safe to run twice.
"""
import sys

COMPOSE = "docker-compose.yml"
SERVICE = """
  console:
    build: ./console
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      POSTGRES_HOST: postgres
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
      CONSOLE_PORT: 8090
    ports:
      - "${CONSOLE_HOST_PORT:-8090}:8090"
"""

text = open(COMPOSE).read()
if "\n  console:" in text:
    print("compose: already has the console service, nothing to do")
    sys.exit(0)
if not text.rstrip().endswith(("- ./data/ollama:/root/.ollama", "/root/.ollama")):
    print("note: appending the console service at the end of the file")
open(COMPOSE, "a").write(SERVICE)
print("compose: console service added on port 8090")
