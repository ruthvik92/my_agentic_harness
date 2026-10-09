ARG BASE_IMAGE=mirror.gcr.io/library/python@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
FROM ${BASE_IMAGE}
RUN apt-get -o Acquire::ForceIPv4=true update && apt-get -o Acquire::ForceIPv4=true install -y --no-install-recommends git ripgrep \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir pytest==9.1.1
RUN apt-get -o Acquire::ForceIPv4=true update && apt-get -o Acquire::ForceIPv4=true install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*
COPY sandbox/pdf_extract.py /opt/local-agent/pdf_extract.py
COPY src/local_agent/executor/worker.py /opt/local-agent/worker.py
COPY sandbox/verify.py /opt/local-agent/verify.py
RUN chmod 0555 /opt/local-agent/worker.py
USER 1000:1000
WORKDIR /workspace
ENTRYPOINT ["python", "-I", "-S", "/opt/local-agent/worker.py"]
