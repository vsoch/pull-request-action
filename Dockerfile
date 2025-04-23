FROM alpine

# docker build -t vanessa/pull-request-action .

LABEL "com.github.actions.name"="Pull Request on Branch Push"
LABEL "com.github.actions.description"="Create a pull request when a branch is created or updated"
LABEL "com.github.actions.icon"="activity"
LABEL "com.github.actions.color"="yellow"

# Newer alpine we are not allowed to install to system python
RUN apk --no-cache add python3 py3-pip py3-virtualenv git bash && \
    python3 -m venv /opt/env && \
    /opt/env/bin/pip3 install --break-system-packages requests
COPY pull-request.py /pull-request.py

RUN chmod u+x /pull-request.py
ENTRYPOINT ["/opt/env/bin/python3", "/pull-request.py"]
