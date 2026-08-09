FROM python:3.11-slim

ARG TZ=Europe/Saratov
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=${TZ}

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata ca-certificates \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./
COPY radar ./radar

RUN useradd -m -u 1000 radar && mkdir -p /app/data && chown -R radar:radar /app
USER radar

CMD ["python", "-u", "main.py"]
