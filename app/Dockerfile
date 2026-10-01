# Intentionally outdated base image and dependencies so the Falcon Cloud Security image
# assessment has real vulnerabilities to report. Do not use these versions in production.
FROM python:3.12.7-alpine3.20
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY . .
USER 1234
EXPOSE 8080
ENTRYPOINT ["python"]
CMD ["app.py"]
