FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 forge \
    && chown -R forge:forge /app
USER forge

EXPOSE 8741

# First page load builds the 12-machine sample if data/warehouse.duckdb is absent.
CMD ["python", "-m", "streamlit", "run", "app/Home.py", "--server.port=8741", "--server.address=0.0.0.0", "--server.headless=true"]
