# Verwende ein offizielles Python-Image als Basis
FROM python:3.9-slim

# Setze das Arbeitsverzeichnis im Container
WORKDIR /usr/src/app

# Kopiere die Dateien requirements.txt und main.py in das Arbeitsverzeichnis
COPY requirements.txt ./
COPY main.py ./

# Installiere benötigte Python-Pakete
RUN pip install --no-cache-dir -r requirements.txt

# Führe das Skript aus, wenn der Container startet
CMD [ "python", "./main.py" ]
