FROM python:3.13.7-alpine3.22

EXPOSE 8000/tcp

WORKDIR /app

COPY pyproject.toml ./
COPY README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["uvicorn"]
CMD ["bento_sts.sts:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]