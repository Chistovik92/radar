FROM python:3.11-slim

ARG TZ=Europe/Saratov
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=${TZ}

# ffmpeg нужен для склейки видео и звука выше 720p. Он заметно увеличивает
# образ (~150 МБ); если загрузка видео не нужна, его можно убрать.
# fonts-dejavu-core — для погоды картинкой: в python:3.11-slim шрифтов нет
# вообще, а встроенный шрифт Pillow кириллицу не покрывает и растровый,
# отчего сводка выходила нечитаемой. Пакет весит около 2 МБ.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata ca-certificates ffmpeg fonts-dejavu-core \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py alembic.ini ./
# Диагностика лежит внутри пакета: tools/ исключён из контекста сборки
COPY radar ./radar
COPY migrations ./migrations

RUN useradd -m -u 1000 radar && mkdir -p /app/data && chown -R radar:radar /app
USER radar

CMD ["python", "-u", "main.py"]
