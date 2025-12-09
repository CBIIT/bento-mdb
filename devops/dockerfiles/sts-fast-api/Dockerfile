FROM python:3.13.11-alpine3.23

EXPOSE 8000/tcp

WORKDIR /app

# Install git for pip to clone from GitHub
RUN apk add --no-cache git

# Install bento-sts-fastapi from GitHub (unreleased)
RUN pip install --no-cache-dir git+https://github.com/CBIIT/bento-sts-fastapi.git@main

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["uvicorn"]
CMD ["bento_sts.sts:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]