FROM python:3.14-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY src ./src
RUN mkdir -p data/uploads data/processed/user_documents data/vector_db
EXPOSE 8000
CMD ["uvicorn", "src.ui.api:app", "--host", "0.0.0.0", "--port", "8000"]
