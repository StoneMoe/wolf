FROM python:3.8-slim

COPY . /app
WORKDIR /app

# RUN pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple
RUN pip install -r requirements.txt

EXPOSE 80

CMD ["python", "main.py"]
