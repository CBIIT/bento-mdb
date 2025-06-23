FROM python:3.13.4-alpine3.22 AS fnl_base_image
EXPOSE 5000/tcp
ADD app /app
WORKDIR /app
RUN pip install bento-sts
RUN pip list | grep bento-sts > STS-VERSION
ENTRYPOINT ["gunicorn"]
