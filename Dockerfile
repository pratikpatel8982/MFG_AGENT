FROM python:3.11-slim

WORKDIR /app

# install uv
RUN pip install uv

# copy project
COPY . .

# install dependencies
RUN uv sync --no-dev

# expose port
EXPOSE 8000

# start server
CMD ["uv","run","gunicorn","backend.app:app","--bind","0.0.0.0:8000"]
