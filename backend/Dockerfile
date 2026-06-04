FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Railway injects $PORT at runtime
ENV PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "gunicorn api:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120 --log-level info"]
