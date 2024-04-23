FROM python:3.9-slim

WORKDIR /usr/src/app

COPY requirements.txt main.py config.json credentials.json ./

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "./main.py"]
