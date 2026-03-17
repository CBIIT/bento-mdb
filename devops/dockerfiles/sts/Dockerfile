FROM python:3.13.11-alpine3.23 AS fnl_base_image
EXPOSE 5000/tcp
RUN apk update && apk upgrade sqlite-libs
ADD app /app
WORKDIR /app
# TODO No longer releasing to PyPI; package name remains bento-sts.
RUN pip install bento-sts
RUN pip install --upgrade cryptography==46.0.5
RUN pip list | grep bento-sts > STS-VERSION
ENTRYPOINT ["gunicorn"]
