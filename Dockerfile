FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl unzip && rm -rf /var/lib/apt/lists/*

# Install deno (JS runtime for yt-dlp)
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh
ENV DENO_DIR=/tmp/deno

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py index.html ./

EXPOSE 5555
CMD ["python", "server.py"]
