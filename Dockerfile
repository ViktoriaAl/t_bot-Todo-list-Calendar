FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir \
    python-telegram-bot \
    Pillow \
    pandas

COPY . .

CMD ["python", "t_bot.py"]