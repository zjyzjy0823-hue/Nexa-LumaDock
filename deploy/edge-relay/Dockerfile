FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY edge_relay.py .

EXPOSE 8090
CMD ["python", "-c", "import uvicorn, edge_relay; uvicorn.run(edge_relay.create_edge_app(), host='0.0.0.0', port=8090)"]
