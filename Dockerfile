FROM python:3.11-alpine

RUN apk add --no-cache openjdk17-jre-headless
RUN apk add --no-cache zip
ENV APP_DIR=/usr/src/app
WORKDIR $APP_DIR
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade -r requirements.txt
COPY delta-patch.jar ./
COPY main.py ./
EXPOSE 8080
CMD ["uvicorn", "main:app", "--forwarded-allow-ips", "*", "--host", "0.0.0.0", "--port", "8080"]

