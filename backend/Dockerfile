# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --prefix=/install -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/local/bin:${PATH}" \
    PORT=8000

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl gosu \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash engageos

COPY --from=builder /install /usr/local
COPY . /app

# The media directory is a Railway volume mount point. Railway mounts empty
# volumes as root:root. The entrypoint (scripts/entrypoint.sh) fixes ownership
# at boot time before dropping to engageos via gosu.
# The memories/ subdirectory holds per-contact AI memory JSON files.
RUN mkdir -p /app/media/memories && chown -R engageos:engageos /app

EXPOSE 8000

ENTRYPOINT ["bash", "scripts/entrypoint.sh"]

# Default command runs the API (advisory-locked migrate + uvicorn).
# Worker / scheduler services override this via their start command.
CMD ["bash", "scripts/start-api.sh"]
