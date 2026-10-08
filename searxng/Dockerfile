FROM docker.io/searxng/searxng:2026.9.30-a9d990033@sha256:a07a5cd2da2c63d66e559f9e4d3a3db106cfc6c32fb0ac70abe91cc28bcd7350

COPY settings.yml /etc/searxng/settings.yml
COPY patch_pinterest_engine.py /tmp/patch_pinterest_engine.py
RUN python /tmp/patch_pinterest_engine.py && rm /tmp/patch_pinterest_engine.py
