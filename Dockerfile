# Verwende ein offizielles Python-Image als Basis
FROM python:3.9-slim

# Setze das Arbeitsverzeichnis im Container
WORKDIR /usr/src/app

# Kopiere die benötigten Dateien in das Arbeitsverzeichnis
COPY requirements.txt main.py config.json credentials.json token.json ./

# Installiere benötigte Python-Pakete
RUN pip install --no-cache-dir -r requirements.txt

# Führe das Skript aus, wenn der Container startet
CMD ["python", "./main.py"]
