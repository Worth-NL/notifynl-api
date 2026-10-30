ARG DOCKER_REGISTRY_PROXY
FROM ${DOCKER_REGISTRY_PROXY}python:3.13-slim-bookworm AS base

COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /uvx /bin/

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV VIRTUAL_ENV="/opt/venv"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    libcurl4 \
    curl \
    && apt-get -y clean && \
    rm -rf /var/lib/apt/lists/* /tmp/*

WORKDIR /home/vcap/app

##### Python Build Image #####################################################
FROM base AS python_build

RUN echo "Install OS dependencies for python app requirements" &&  \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libcurl4-openssl-dev \
    libssl-dev && \
    apt-get -y clean && \
    rm -rf /var/lib/apt/lists/* /tmp/*

COPY requirements.txt .
COPY requirements_nl.txt .

ENV UV_CACHE_DIR='/tmp/uv-cache/'
RUN echo "Installing python requirements" && \
    python3 -m venv /opt/venv && \
    uv pip sync --trusted-host git.lpc.logius.nl --trusted-host pypi.org --trusted-host github.com --trusted-host pypi.python.org --trusted-host=files.pythonhosted.org --python /opt/venv/bin/python requirements_nl.txt

COPY . .
RUN make generate-version-file  # This file gets copied across

##### Production Image #######################################################
FROM base AS production

# Gewijzigd door NotO: user aanmaken + logs dir in 1 laag i.p.v. meerder
RUN groupadd -r notify \
    && useradd -r -g notify notify \
    && mkdir -p /home/vcap/logs \
    && chown -R notify:notify /home/vcap
USER notify

COPY --from=python_build --chown=notify:notify /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY --chown=notify:notify app app
COPY --chown=notify:notify migrations migrations
COPY --chown=notify:notify templates templates
COPY --chown=notify:notify run_celery.py gunicorn_config.py application.py entrypoint.sh ./
COPY --from=python_build --chown=notify:notify /home/vcap/app/app/version.py app/version.py

RUN python -m compileall . && \
    chmod +x /home/vcap/app/entrypoint.sh

ENTRYPOINT [ "/home/vcap/app/entrypoint.sh" ]

##### Test Image ##############################################################
FROM production AS test

USER root
RUN echo "Install OS dependencies for test build" && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      sudo \
      make \
      curl \
      git && \
    apt-get -y clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* \
    && usermod -aG sudo notify \
    && echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
USER notify

COPY --chown=notify:notify Makefile requirements_for_test.txt requirements_nl_test.txt ./
ENV UV_CACHE_DIR='/tmp/uv-cache/'
RUN make bootstrap-nl

COPY --chown=notify:notify . .

##### Concourse Test Image ####################################################
FROM production AS concourse_tests

SHELL ["/bin/bash", "-c"]

ENV POSTGRES_VERSION=15

USER root
RUN echo "Install OS dependencies for test build" && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      sudo \
      libcurl4-openssl-dev \
      libssl-dev \
      make \
      git \
      postgresql-${POSTGRES_VERSION} \
      postgresql-client-${POSTGRES_VERSION} && \
    apt-get -y clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* \
    && usermod -aG sudo notify \
    && echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers \
    && service postgresql start \
    && su - postgres -c "psql -c \"alter user postgres with password 'postgres';\"" \
    && service postgresql stop

USER notify

COPY --chown=notify:notify . .

ENV SQLALCHEMY_DATABASE_URI=postgresql://postgres:postgres@localhost/
ENV UV_CACHE_DIR='/tmp/uv-cache/'
RUN uv pip sync --trusted-host git.lpc.logius.nl --trusted-host pypi.org --trusted-host github.com --trusted-host pypi.python.org --trusted-host=files.pythonhosted.org requirements_nl_test.txt