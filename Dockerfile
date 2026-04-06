FROM python:3.12-slim

WORKDIR /src

COPY . .
RUN pip install --no-cache-dir .

CMD ["python", "-m", "app.main"]
