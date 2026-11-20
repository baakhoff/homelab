# lab-mcp: the homelab's services as MCP tools, for an agent that runs
# outside the cluster (clusters/lab/lab-mcp/README.md says what and why).
#
# A small Python server and nothing else: every tool is an HTTP call to a
# service in the cluster, or pypdf working on a file in the scratch volume.
# The version in VERSION is the image's tag; the Deployment pins it.
FROM python:3.13.18-slim-trixie

# Debian's fixes since the base image was built, for the CVE scan in the
# workflow.
RUN apt-get update \
 && apt-get upgrade -y \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lab_mcp lab_mcp

# The root filesystem is read-only in the pod: no bytecode files, and HOME
# on the scratch volume for any library that wants one.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp

USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "lab_mcp"]
