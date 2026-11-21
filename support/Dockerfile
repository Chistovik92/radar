FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
ARG SUPPORT_AI=0
COPY support/requirements.txt support/requirements-ai.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && if [ "$SUPPORT_AI" = "1" ]; then pip install --no-cache-dir -r /tmp/requirements-ai.txt; fi
COPY support /app/support
RUN mkdir -p /app/data/exports
CMD ["python", "-m", "support"]
