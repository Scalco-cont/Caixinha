FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5001

# Gunicorn com 4 workers e --preload para eliminar cold start
# --preload: carrega o app UMA vez no processo pai antes de abrir os workers
# --workers 4: 4 "atendentes" paralelos para multiplos usuarios simultaneos
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "4", "--timeout", "120", "--preload", "app:app"]