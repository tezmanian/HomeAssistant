FROM python:3.13-slim

RUN pip install --no-cache-dir jinja2==3.1.6 pyyaml==6.0.3 yamllint==1.37.1

WORKDIR /work
CMD ["python", "-I", "tools/check_blueprints.py"]
