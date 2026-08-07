FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Не root: боту не нужны права на запись куда-либо кроме каталога учёта
# (USAGE_FILE), поэтому создаём непривилегированного пользователя и отдаём ему
# только /app/data — сам код остаётся доступным лишь на чтение.
RUN useradd --create-home --uid 10001 botuser \
    && mkdir -p /app/data \
    && chown -R botuser:botuser /app/data
USER botuser

CMD ["python", "main.py"]
