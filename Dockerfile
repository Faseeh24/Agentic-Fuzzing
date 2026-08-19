#
# Dockerfile — build the mxml harness with ASan + UBSan.
# Based on debian:trixie-slim which ships gcc with sanitizer support.
#
# Build:
#   docker build -t mxml-harness .
#
# Compile:
#   docker run --rm -v "$(pwd)":/src mxml-harness make -C /src/harness
#
# Run sample tests:
#   docker run --rm -v "$(pwd)":/src mxml-harness make -C /src/harness test
#
# Run the full agentic fuzzing pipeline:
#   docker compose up
#

FROM debian:trixie-slim

# Install gcc, make, python3, and sanitizer runtime
RUN apt-get update && apt-get install -y \
        gcc \
        make \
        python3 \
        python3-pip \
        python3-venv \
        libasan8 \
        libubsan1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python fuzzing / LLM / grammar dependencies
COPY requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install -r /tmp/requirements.txt

# Copy project source
WORKDIR /src
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH=/src

# Default: build harness and run sample tests
CMD ["make", "-C", "/src/harness", "all", "test"]
