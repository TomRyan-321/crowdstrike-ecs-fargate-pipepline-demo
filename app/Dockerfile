FROM python:3.13-alpine
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY . .
USER 1234
EXPOSE 8080
ENTRYPOINT ["python"]
CMD ["app.py"]
