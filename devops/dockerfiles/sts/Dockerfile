FROM python:3.13.3-alpine3.21 AS fnl_base_image
EXPOSE 5000/tcp
ENV NEO4J_MDB_URI=bolt://localhost:7687 \
    NEO4J_MDB_USER=neo4j \
    NEO4J_MDB_PASS=neo4j1 \
    STS_PORT=5000 \
    STS_LOGLEVEL=info
ADD app /app
WORKDIR /app
RUN pip install bento-sts
RUN pip list | grep bento-sts > STS-VERSION
ENTRYPOINT ["gunicorn"]
