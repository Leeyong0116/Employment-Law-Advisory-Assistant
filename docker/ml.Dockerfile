# ML runtime for indexing (and later retrieval): Python 3.12 + CUDA PyTorch.
#
# Why a container: on the Windows dev machine, Smart App Control blocks some
# native DLLs these packages ship (scipy). Linux in the container is not
# subject to it. The same image can run on the Sunway HPC via Apptainer, so
# local and HPC runs share one environment.
#
# The source tree is mounted at /app at run time (docker-compose.yml), so
# code changes need no rebuild; only dependency changes do.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

WORKDIR /app
