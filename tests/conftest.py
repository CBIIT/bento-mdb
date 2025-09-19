import os
import subprocess
from time import sleep

import pytest
import requests

wait = 25


def is_responsive(url):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return True
    except ConnectionError:
        return False


@pytest.fixture(scope="session")
def mdb_versioned(docker_services, docker_ip):
    """Start a container with the mdb-versioned image."""
    bolt_port = docker_services.port_for("mdb-versioned", 7687)
    http_port = docker_services.port_for("mdb-versioned", 7474)
    bolt_url = f"bolt://{docker_ip}:{bolt_port}"
    http_url = f"http://{docker_ip}:{http_port}"
    sleep(wait)
    docker_services.wait_until_responsive(
        timeout=30.0,
        pause=0.1,
        check=lambda: is_responsive(http_url),
    )
    return bolt_url, http_url


@pytest.fixture(scope="session")
def prefect_worker(docker_services, docker_ip):
    """Start a container with the prefect-worker image."""
    http_port = docker_services.port_for("prefect-worker", 7475)
    http_url = f"http://{docker_ip}:{http_port}"
    sleep(wait)
    docker_services.wait_until_responsive(
        timeout=30.0,
        pause=0.1,
        check=lambda: is_responsive(http_url),
    )
    return "prefect-worker"


@pytest.fixture
def run_prefect_flow(docker_services, mdb_versioned, prefect_worker):
    """Fixture to run a Prefect flow in the worker container."""

    def _run_flow(flow_script, flow_name, *args, **kwargs):
        current_dir = os.path.dirname(os.path.dirname(__file__))
        abs_flow_script = os.path.join(current_dir, flow_script)
        container_flow_path = os.path.relpath(abs_flow_script, current_dir)

        cmd = [
            "docker-compose",
            "-f",
            os.path.join(os.path.dirname(__file__), "docker-compose.yml"),
            "exec",
            "-T",
            "prefect-worker",
            "python",
            container_flow_path,
            flow_name,
        ]
        for arg in args:
            cmd.append(str(arg))
        for key, value in kwargs.items():
            cmd.append(f"--{key}={value}")
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        return result

    return _run_flow
