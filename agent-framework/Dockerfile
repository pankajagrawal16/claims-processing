FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8088
WORKDIR /app
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt .
RUN pip install --no-cache-dir ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} -r requirements.txt
COPY main.py workflow.py ./
RUN useradd --create-home --uid 10001 claims && chown -R claims:claims /app
USER claims
EXPOSE 8088
CMD ["python", "main.py"]
