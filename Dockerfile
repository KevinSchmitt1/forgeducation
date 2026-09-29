# forgeducation — local, single-tenant, bring-your-own-key front door (doc 25).
#
#   docker build -t forgeducation .
#   docker run --rm -p 7860:7860 -v "$PWD/runs:/app/runs" forgeducation
#   → open http://localhost:7860 and paste your API key in the page
#
# The container is the distribution unit AND the sandbox the generated notebooks run in.
# One user per container; the key stays in this container's memory.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GRADIO_ANALYTICS_ENABLED=False

RUN useradd --create-home --uid 1000 forged
WORKDIR /app

# Dependencies first (cached layer), then the source.
COPY pyproject.toml README.md ./
COPY forged ./forged
COPY personas ./personas
COPY config ./config
COPY templates ./templates

# Editable on purpose: the bundled personas/ and config/ live at the repo root, outside
# the `forged` package, and are located relative to it (cli.PACKAGE_ROOT). A plain wheel
# install would import fine but could not find them.
RUN pip install -e '.[ui]' \
    && python -m ipykernel install --name python3 --prefix /usr/local \
    && mkdir -p /app/runs && chown -R forged:forged /app

USER forged
EXPOSE 7860
# 0.0.0.0 inside the container; publish with -p 127.0.0.1:7860:7860 to stay local-only.
CMD ["forged", "ui", "--host", "0.0.0.0", "--port", "7860", "--runs", "/app/runs"]
