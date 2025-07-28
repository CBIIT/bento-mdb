FROM python:3.13.5-alpine3.22 AS fnl_base_image
EXPOSE 5000/tcp
RUN apk update && apk upgrade sqlite-libs
ADD app /app
WORKDIR /app
RUN pip install bento-sts
RUN pip list | grep bento-sts > STS-VERSION
ENTRYPOINT ["gunicorn"]
