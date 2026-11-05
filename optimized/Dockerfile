FROM node:22-alpine AS frontend
WORKDIR /src/client
COPY client/package*.json ./
RUN npm install --no-audit --no-fund
COPY client/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt
COPY server/ ./server/
COPY --from=frontend /src/client/dist ./client/dist
WORKDIR /app/server
ENV PORT=8000 PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "-m", "app.main"]
