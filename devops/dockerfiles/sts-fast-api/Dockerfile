FROM python:3.14.4-slim-bookworm

EXPOSE 8000/tcp

WORKDIR /app

RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends git curl && \
    rm -rf /var/lib/apt/lists/*

# Replace pip with uv and remove pip to eliminate PRISMA-2022-0168
RUN pip install --no-cache-dir uv && \
    pip uninstall -y pip

# Install bento-sts-fastapi from GitHub using uv (no pip in final image)
RUN uv pip install --no-cache --system git+https://github.com/CBIIT/bento-sts-fastapi.git@main

ENV PYTHONUNBUFFERED=1

# Create non-root user for security
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -s /sbin/nologin -M appuser

USER appuser
ENTRYPOINT ["uvicorn"]
CMD ["bento_sts.sts:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
