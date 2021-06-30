FROM alpine

# docker build -t vanessa/pull-request-action .

LABEL "com.github.actions.name"="Pull Request on Branch Push"
LABEL "com.github.actions.description"="Create a pull request when a branch is created or updated"
LABEL "com.github.actions.icon"="activity"
LABEL "com.github.actions.color"="yellow"

ENV HTTP_PROXY=$HTTP_PROXY
ENV HTTPS_PROXY=$HTTPS_PROXY
ENV NO_PROXY=$NO_PROXY

RUN apk --no-cache add python3 py3-pip git bash && \
    pip3 install requests
COPY pull-request.py /pull-request.py

RUN chmod u+x /pull-request.py
ENTRYPOINT ["python3", "/pull-request.py"]
