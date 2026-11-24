FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AI_COMPANY_DB=/data/company.sqlite AI_HOST=0.0.0.0 AI_PORT=8443
WORKDIR /app
RUN groupadd --gid 10001 orbit && useradd --uid 10001 --gid 10001 --no-create-home orbit && mkdir /data && chown 10001:10001 /data
COPY backend/ /app/backend/
COPY web/ /app/web/
COPY tools/ /app/tools/
USER 10001:10001
EXPOSE 8443
CMD ["python","backend/server.py"]
