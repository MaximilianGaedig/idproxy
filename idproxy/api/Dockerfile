FROM python:3.11-alpine

WORKDIR /app

RUN mkdir -p /socket && chmod 777 /socket

COPY requirements.txt .

RUN apk add --no-cache curl bash busybox-suid \
    && apk add --no-cache --virtual .build-deps gcc musl-dev \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && apk del .build-deps

COPY idproxy.py pypush_gsa_icloud.py  .

CMD ["python", "idproxy.py"]
