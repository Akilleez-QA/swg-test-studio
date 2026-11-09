FROM docker.io/library/python:3.12-slim-bookworm@sha256:0f086103b026048cc50cb5da25ec435c023c5241a83fc44daea593377abc61c4
WORKDIR /studio
COPY README.md pyproject.toml swg-tests.py swg-tests.ps1 build_release.py Dockerfile .dockerignore ./
COPY swg_test_studio/ swg_test_studio/
COPY tests/ tests/
RUN python -B build_release.py --output /build/swg-test-studio.zip
USER 65534:65534
CMD ["python", "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]
