FROM python:3.11-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir markdown

COPY . /build

RUN python docs/generate_docs.py

FROM nginx:alpine

COPY docs/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/docs_site /usr/share/nginx/html

EXPOSE 80
