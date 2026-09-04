# Ubuntu Server requirements review

Reviewed 2026-09-04 against the repository and first-party package sources.

## Verdict

The repository now targets Ubuntu Server 26.04 LTS with Python 3.14 and FFmpeg 8.x. This update corrected four problems found during the review:

- The README previously said Python 3.8+, but current FastAPI, Uvicorn, `python-multipart`, and `python-dotenv` releases require Python 3.10 or newer. ([FastAPI](https://pypi.org/project/fastapi/), [Uvicorn](https://pypi.org/project/uvicorn/), [python-multipart](https://pypi.org/project/python-multipart/), [python-dotenv](https://pypi.org/project/python-dotenv/))
- The production dependencies were unpinned. `requirements.txt` now locks the complete resolver set. ([pip: Repeatable installs](https://pip.pypa.io/en/stable/topics/repeatable-installs/))
- Test packages shared the production requirements file. `requirements-dev.txt` now contains the test-only packages, and the unused `pytest-asyncio` dependency has been removed. ([production requirements](requirements.txt), [test requirements](requirements-dev.txt), [tests](test.py))
- The README claimed 20 concurrent requests while the application caps media processing at 10 concurrent jobs per process. The README now matches the configured semaphore. ([README](README.md#features), [configured semaphore](main.py#L28))

FFmpeg remains a host dependency. Both `ffmpeg` and `ffprobe` must be on `PATH`; the application invokes them directly. Railway and Nixpacks already install the `ffmpeg` system package. ([application calls](main.py), [Railpack config](railpack.json), [Nixpacks config](nixpacks.toml))

## Recommended Ubuntu baseline

Use **Ubuntu Server 26.04 LTS** for this deployment. It remains in standard support through 2031. ([Ubuntu release cycle](https://ubuntu.com/about/release-cycle))

- Ubuntu 26.04 supplies Python 3.14 and FFmpeg 8.0.1. ([Ubuntu Python package](https://packages.ubuntu.com/resolute/python3.14), [Ubuntu FFmpeg package](https://packages.ubuntu.com/resolute/ffmpeg))
- A test fixture uses `-display_rotation`, which FFmpeg added to its CLI in October 2022. Ubuntu 22.04's FFmpeg 4.4 predates it, so 22.04 cannot run the current test suite unchanged. ([repository test](test.py#L139), [FFmpeg addition](https://ffmpeg.org/pipermail/ffmpeg-cvslog/2022-October/134898.html), [Ubuntu 22.04 FFmpeg](https://packages.ubuntu.com/en/jammy/ffmpeg))
- On Ubuntu, install Python packages inside a virtual environment. Ubuntu explicitly warns against using pip in its externally managed system Python. ([Ubuntu Python guidance](https://documentation.ubuntu.com/ubuntu-for-developers/tutorials/python-use/))

Suggested host bootstrap:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Ubuntu documents `python3` as the distribution's default Python, `venv` for isolated environments, and `python3-pip` for installing packages in them. ([Ubuntu Python setup](https://documentation.ubuntu.com/ubuntu-for-developers/howto/python-setup/), [Ubuntu virtual environment guide](https://documentation.ubuntu.com/ubuntu-for-developers/tutorials/python-use/))

## Python 3.14 target

Python 3.14 is the deployment target for Ubuntu 26.04. The pinned FastAPI, Uvicorn, Pydantic 2, `python-multipart`, `python-dotenv`, pytest, and HTTPX2 releases advertise Python 3.14 support. ([FastAPI](https://pypi.org/project/fastapi/), [Uvicorn](https://pypi.org/project/uvicorn/), [Pydantic](https://pypi.org/project/pydantic/), [python-multipart](https://pypi.org/project/python-multipart/), [python-dotenv](https://pypi.org/project/python-dotenv/), [pytest](https://pypi.org/project/pytest/), [HTTPX2](https://pypi.org/project/httpx2/))

`httpx` 0.28.1 permits Python 3.14 by its `Requires-Python` range but does not list a Python 3.14 classifier. Its pinned `httpcore` 1.0.9 dependency includes the known Python 3.14 import fix. HTTPX2 is pinned for Starlette's test client, while the application keeps HTTPX for outbound media downloads. ([HTTPX metadata](https://pypi.org/project/httpx/), [httpcore 1.0.8 fix](https://pypi.org/project/httpcore/), [HTTPX2](https://pypi.org/project/httpx2/))

pip successfully resolved every pinned package to a CPython 3.14 Linux wheel or a platform-independent wheel. The native `pydantic_core` package has CPython 3.14 wheels for both x86-64 and ARM64 Linux. ([pydantic-core files](https://pypi.org/project/pydantic-core/2.46.5/))

The same pinned set installed cleanly in the local Python 3.13 environment, passed `pip check`, and passed all 31 repository tests with FFmpeg 8.0. The exact application test suite was not executed under Python 3.14 because that interpreter was not available locally; the Python 3.14 Linux check covered dependency resolution and wheel availability.

## Published requirements

> - Ubuntu Server 26.04 LTS
> - Python 3.14 for the production deployment, using Ubuntu's `python3` in a virtual environment
> - FFmpeg 8.x with `ffmpeg` and `ffprobe` available on `PATH`
> - Writable `temp/` and `output/` storage sized for input and rendered media
> - CPU and memory sized by measured FFmpeg workload and configured concurrency

Do not advertise a fixed low RAM/CPU minimum without load testing. Ubuntu 26.04 Server itself can start at 1.5 GB RAM and 4 GB storage, but Canonical says server sizing depends on the use case; transcoding capacity is workload-dependent. ([Ubuntu 26.04 requirements](https://documentation.ubuntu.com/release-notes/26.04/))

The current limit is 10 media jobs per server process. Multiple Uvicorn workers would each create their own 10-job semaphore, so server sizing must account for the worker count. ([configured semaphore](main.py#L28))
