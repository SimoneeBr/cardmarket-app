# Cardmarket Companion - browser agent (Playwright + Chromium)
# The Playwright image ships Chromium and all system dependencies.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DISPLAY=:99 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH=/opt/venv/bin:$PATH

# Virtual display + optional remote viewer (noVNC) used ONLY for manual pairing.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-venv xvfb x11vnc novnc websockify tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY packages/shared /opt/shared
COPY apps/agent /app
# Own virtualenv: never fight the distro's Python packages. Browsers stay in /ms-playwright.
RUN python3 -m venv /opt/venv && pip install /opt/shared /app \
 && python -c "import playwright; print('playwright ok')"

COPY infrastructure/docker/agent-entrypoint.sh /usr/local/bin/agent-entrypoint
RUN chmod +x /usr/local/bin/agent-entrypoint \
 && mkdir -p /data/browser-profile /data/artifacts /data/mock \
 && chown -R pwuser:pwuser /data

USER pwuser
EXPOSE 6080
# Application-level: event loop alive AND recent successful API contact.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD ["python", "-m", "agent", "healthcheck"]
ENTRYPOINT ["tini", "--", "agent-entrypoint"]
CMD ["run"]
