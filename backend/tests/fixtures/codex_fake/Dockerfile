FROM python:3.12-slim-bookworm

RUN useradd --create-home --uid 10001 codex-test
WORKDIR /opt/fake-codex
COPY fake_codex.py /opt/fake-codex/fake_codex.py
RUN chmod 0555 /opt/fake-codex/fake_codex.py
USER codex-test
ENTRYPOINT ["python", "/opt/fake-codex/fake_codex.py"]
