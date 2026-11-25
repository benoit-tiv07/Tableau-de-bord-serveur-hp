FROM python:3.12-slim

# L'image slim n'a pas la commande ping
RUN apt-get update && apt-get install -y --no-install-recommends iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py bbox.py ./
COPY templates templates
COPY static static

# Pour que les print() apparaissent tout de suite dans les logs
ENV PYTHONUNBUFFERED=1

CMD ["python", "app.py"]
