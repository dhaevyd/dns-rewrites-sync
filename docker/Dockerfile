FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/dhaevyd/dns-rewrites-sync" \
      org.opencontainers.image.version="1.1.0" \
      org.opencontainers.image.description="DNS rewrite sync hub-and-spoke tool"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gosu \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 1001 appuser \
 && useradd --uid 1001 --gid appuser --no-create-home appuser \
 && mkdir -p /var/lib/dns-sync \
 && chown appuser:appuser /var/lib/dns-sync

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY dns_sync/ dns_sync/

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "dns_sync.app:app", "--host", "0.0.0.0", "--port", "8000"]
