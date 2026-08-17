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

FROM debian:trixie-slim

# Install gcc, make, and the sanitizer runtime packages
RUN apt-get update && apt-get install -y \
        gcc \
        make \
        python3 \
        python3-pip \
        libasan8 \
        libubsan1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python fuzzing / LLM dependencies
RUN pip3 install --break-system-packages \
        hypothesis \
        httpx \
        python-dotenv \
        google-generativeai

# Copy the project source into the image
WORKDIR /src

# Default command: build and run sample tests
CMD ["make", "-C", "/src/harness", "all", "test"]
