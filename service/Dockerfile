FROM python:3.13-slim
WORKDIR /app
COPY service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY caderno ./caderno
COPY service/caderno_service ./caderno_service
ENV PYTHONUNBUFFERED=1
EXPOSE 8420
CMD ["python", "-m", "caderno_service.server"]
