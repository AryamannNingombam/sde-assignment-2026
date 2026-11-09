# One image for both the simulator and the controller (different commands in docker-compose.yml).
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY controller ./controller
COPY sim ./sim
COPY scenarios ./scenarios
COPY run.sh ./run.sh
RUN chmod +x run.sh
ENV PYTHONUNBUFFERED=1 CTRL_STATE_DIR=/state
