FROM python:3.11

# Install build dependencies (gcc) only
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install --no-cache-dir poetry

# Build metadata (optional)
ARG GIT_REVISION=dev
ENV GIT_REVISION=$GIT_REVISION

# Avoid writing .pyc/__pycache__ and ensure unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1


# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml poetry.toml .python-version poetry.lock /app/

# Install Python dependencies with Poetry
RUN poetry install --no-root

# Copy the rest of the application
COPY . /app/

# Optionally enforce that migrations exist at build-time
# Set REQUIRE_MIGRATIONS=1 to enforce in CI; default relaxed for first-time Docker init
ARG REQUIRE_MIGRATIONS=0
RUN if [ "$REQUIRE_MIGRATIONS" = "1" ] && [ ! -d /app/migrations ]; then \
      echo -e "\n=========\nNO MIGRATIONS FOUND. RUN docker compose run --rm migrate\n=========\n" >&2; \
      exit 1; \
    fi

# Expose port 5000
EXPOSE 5000

# Set the default command with retry for migrations
CMD ["poetry", "run", "python3", "-m", "spooky.bot"]
