# The same immutable image runs either independent service.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN pip install --no-deps . && useradd --uid 10001 --create-home bot
USER bot
CMD ["python", "-m", "mcp_server.main"]
