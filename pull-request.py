#!/usr/bin/env python3

import sys
import os
import json
import requests

################################################################################
# Helper Functions
################################################################################


def get_envar(name):
    value = os.environ.get(name)
    if not value:
        sys.exit("%s is required for vsoch/pull-request-action" % name)
    return value


def check_events_json():
    events = get_envar("GITHUB_EVENT_PATH")
    if not os.path.exists(events):
        sys.exit("Cannot find Github events file at ${GITHUB_EVENT_PATH}")
    print("Found ${GITHUB_EVENT_PATH} at %s" % events)
    return events


def abort_if_fail(reason):
    """If FAIL_ON_ERROR, exit with an error and print some rationale"""
    if os.environ.get("FAIL_ON_ERROR"):
        sys.exit(reason)
    print("Error, but FAIL_ON_ERROR is not set, continuing: %s" % reason)


def parse_into_list(values):
    values = values.replace('"', "").replace("'", "")
    if not values:
        return []
    return ['"%s"' % x.strip() for x in values.split(" ")]


################################################################################
# Global Variables (we can't use GITHUB_ prefix)
################################################################################

API_VERSION = "v3"
BASE = "https://api.github.com"

HEADERS = {
    "Authorization": "token %s" % get_envar("GITHUB_TOKEN"),
    "Accept": "application/vnd.github.%s+json;application/vnd.github.antiope-preview+json;application/vnd.github.shadow-cat-preview+json"
    % API_VERSION,
}

# URLs
REPO_URL = "%s/repos/%s" % (BASE, get_envar("GITHUB_REPOSITORY"))
ISSUE_URL = "%s/issues" % REPO_URL
PULLS_URL = "%s/pulls" % REPO_URL


def create_pull_request(
    source,
    target,
    body,
    title,
    assignees,
    reviewers,
    team_reviewers,
    is_draft=False,
    can_modify=True,
):

    # Check if the branch already has a pull request open
    data = {"base": target, "head": source, "body": body}
    response = requests.get(PULLS_URL, json=data)
    if response.status_code != 200:
        abort_if_fail(
            "Unable to retrieve information about pull requests: %s: %s"
            % (response.status_code, response.reason)
        )

    response = response.json()
    print("::group::github pr response")
    print(response)
    print("::endgroup::github pr response")

    # Option 1: The pull request is already open
    if response:
        pull_request = response[0].get("head", {}).get("ref", "")
        if pull_request == source:
            print("Pull request from %s to %s is already open!" % (source, target))

    # Option 2: Open a new pull request
    else:
        # Post the pull request
        data = {
            "title": title,
            "body": body,
            "base": target,
            "head": source,
            "draft": is_draft,
            "maintainer_can_modify": can_modify,
        }
        response = requests.post(PULLS_URL, json=data, headers=HEADERS)
        if response.status_code != 201:
            abort_if_fail(
                "Unable to create pull request: %s: %s, %s"
                % (
                    response.status_code,
                    response.reason,
                    response.json().get("message", ""),
                )
            )

        # Expected return codes are 0 for success
        pull_request_return_code = (
            0 if response.status_code == 201 else response.status_code
        )
        response = response.json()
        print("::group::github response")
        print(response)
        print("::endgroup::github response")
        number = response.get("number")
        html_url = response.get("html_url")
        print("Number opened for PR is %s" % number)
        print("::set-env name=PULL_REQUEST_NUMBER::%s" % number)
        print("::set-output name=pull_request_number::%s" % number)
        print("::set-env name=PULL_REQUEST_RETURN_CODE::%s" % pull_request_return_code)
        print(
            "::set-output name=pull_request_return_code::%s" % pull_request_return_code
        )
        print("::set-env name=PULL_REQUEST_URL::%s" % html_url)
        print("::set-output name=pull_request_url::%s" % html_url)

        if assignees:

            # Remove leading and trailing quotes
            assignees = parse_into_list(assignees)

            print(
                "Attempting to assign %s to pull request with number %s"
                % (assignees, number)
            )

            # POST /repos/:owner/:repo/issues/:issue_number/assignees
            data = {"assignees": assignees}
            ASSIGNEES_URL = "%s/%s/assignees" % (ISSUE_URL, number)
            response = requests.post(ASSIGNEES_URL, json=data, headers=HEADERS)
            if response.status_code != 201:
                abort_if_fail(
                    "Unable to create assignees: %s: %s, %s"
                    % (
                        response.status_code,
                        response.reason,
                        response.json().get("message", ""),
                    )
                )

            assignees_return_code = (
                0 if response.status_code == 201 else response.status_code
            )
            print("::set-env name=ASSIGNEES_RETURN_CODE::%s" % assignees_return_code)
            print("::set-output name=assignees_return_code::%s" % assignees_return_code)

        if reviewers or team_reviewers:

            print(
                "Found reviewers: %s and team reviewers: %s"
                % (reviewers, team_reviewers)
            )
            team_reviewers = parse_into_list(team_reviewers)
            reviewers = parse_into_list(reviewers)
            print(
                "Parsed reviewers: %s and team reviewers: %s"
                % (reviewers, team_reviewers)
            )

            # POST /repos/:owner/:repo/pulls/:pull_number/requested_reviewers
            REVIEWERS_URL = "%s/%s/requested_reviewers" % (PULLS_URL, number)

            data = {"reviewers": reviewers, "team_reviewers": team_reviewers}
            response = requests.post(REVIEWERS_URL, json=data, headers=HEADERS)
            if response.status_code != 201:
                abort_if_fail(
                    "Unable to assign reviewers: %s: %s, %s"
                    % (
                        response.status_code,
                        response.reason,
                        response.json().get("message", ""),
                    )
                )

            reviewers_return_code = (
                0 if response.status_code == 201 else response.status_code
            )
            response = response.json()
            print("::group::github reviewers response")
            print(response)
            print("::endgroup::github reviewers response")
            print("::set-env name=REVIEWERS_RETURN_CODE::%s" % reviewers_return_code)
            print("::set-output name=reviewers_return_code::%s" % reviewers_return_code)
            print("Add reviewers return code: %s" % reviewers_return_code)


def main():

    # path to file that contains the POST response of the event
    # Example: https://github.com/actions/bin/tree/master/debug
    # Value: /github/workflow/event.json
    check_events_json()

    branch_prefix = os.environ.get("BRANCH_PREFIX", "")
    print("Branch prefix is %s" % branch_prefix)
    if not branch_prefix:
        print("No branch prefix is set, all branches will be used.")

    # Default to master to support older, will eventually change to main
    pull_request_branch = os.environ.get("PULL_REQUEST_BRANCH", "master")
    print("Pull requests will go to %s" % pull_request_branch)

    # Pull request draft
    pull_request_draft = os.environ.get("PULL_REQUEST_DRAFT")
    if not pull_request_draft:
        print("No explicit preference for draft PR: created PRs will be normal PRs.")
        pull_request_draft = False
    else:
        print(
            "Environment variable PULL_REQUEST_DRAFT set to a value: created PRs will be draft PRs."
        )
        pull_request_draft = True

    # Maintainer can modify, defaults to CAN, unless user sets MAINTAINER_CANT_MODIFY
    maintainer_can_modify = os.environ.get("MAINTAINER_CANT_MODIFY")
    if not maintainer_can_modify:
        print(
            "No explicit preference for maintainer being able to modify: default is true."
        )
        maintainer_can_modify = True
    else:
        print(
            "Environment variable MAINTAINER_CANT_MODIFY set to a value: maintainer will not be able to modify."
        )
        maintainer_can_modify = False

    # Assignees
    assignees = os.environ.get("PULL_REQUEST_ASSIGNEES")
    if not assignees:
        print("PULL_REQUEST_ASSIGNEES is not set, no assignees.")
    else:
        print("PULL_REQUEST_ASSIGNEES is set, %s" % assignees)

    # Reviewers (individual and team)

    reviewers = os.environ.get("PULL_REQUEST_REVIEWERS")
    team_reviewers = os.environ.get("PULL_REQUEST_TEAM_REVIEWERS")
    if not reviewers:
        print("PULL_REQUEST_REVIEWERS is not set, no reviewers.")
    else:
        print("PULL_REQUEST_REVIEWERS is set, %s" % reviewers)

    if not team_reviewers:
        print("PULL_REQUEST_TEAM_REVIEWERS is not set, no team reviewers.")
    else:
        print("PULL_REQUEST_TEAM_REVIEWERS is set, %s" % team_reviewers)

    # The user is allowed to explicitly set the name of the branch
    branch = os.environ.get("PULL_REQUEST_FROM_BRANCH")
    if not branch:
        print("PULL_REQUEST_FROM_BRANCH is not set, checking branch in payload.")
        with open(check_events_json(), "r") as fd:
            branch = json.loads(fd.read()).get("ref")
        branch = branch.replace("refs/heads/", "")
    else:
        print("PULL_REQUEST_FROM_BRANCH is set.")

    # At this point, we must have a branch
    if branch:
        print("Found branch %s to open PR from" % branch)
    else:
        sys.exit(
            "No branch in payload, you are required to define PULL_REQUEST_FROM_BRANCH in the environment."
        )

    # If it's to the target branch, ignore it

    if branch == pull_request_branch:
        print("Target and current branch are identical (%s), skipping." % branch)
    else:

        # If the prefix for the branch matches
        if not branch_prefix or branch.startswith(branch_prefix):

            # Pull request body (optional)
            pull_request_body = os.environ.get(
                "PULL_REQUEST_BODY",
                "This is an automated pull request to update from branch %s" % branch,
            )
            print("Pull request body is %s" % pull_request_body)

            # Pull request title (optional)
            pull_request_title = os.environ.get(
                "PULL_REQUEST_TITLE", "Update from %s" % branch
            )
            print("Pull request title is %s" % pull_request_title)

            # Create the pull request
            create_pull_request(
                target=pull_request_branch,
                source=branch,
                body=pull_request_body,
                title=pull_request_title,
                is_draft=pull_request_draft,
                can_modify=maintainer_can_modify,
                assignees=assignees,
                reviewers=reviewers,
                team_reviewers=team_reviewers,
            )


if __name__ == "__main__":
    print("==========================================================================")
    print("START: Running Pull Request on Branch Update Action!")
    main()
    print("==========================================================================")
    print("END: Finished")
