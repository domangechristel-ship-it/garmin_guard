FROM python:3.12-slim

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY package_folder package_folder
COPY src src

ENV ENV=prod

CMD uvicorn package_folder.api_file:app --host 0.0.0.0 --port $PORT
