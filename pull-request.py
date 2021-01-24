#!/usr/bin/env python3

import sys
import os
import json
import requests

################################################################################
# Helper Functions
################################################################################


def get_envar(name):
    """
    Given a name, return the corresponding environment variable. Exit if not
    defined, as using this function indicates the envar is required.

    Parameters:
    name (str): the name of the environment variable
    """
    value = os.environ.get(name)
    if not value:
        sys.exit("%s is required for vsoch/pull-request-action" % name)
    return value


def check_events_json():
    """the github events json is required in order to indicate that we are
    in an action environment.
    """
    events = get_envar("GITHUB_EVENT_PATH")
    if not os.path.exists(events):
        sys.exit("Cannot find Github events file at ${GITHUB_EVENT_PATH}")
    print("Found ${GITHUB_EVENT_PATH} at %s" % events)
    return events


def abort_if_fail(response, reason):
    """If PASS_ON_ERROR, don't exit. Otherwise exit with an error and print
    the reason.

    Parameters:
    response (requests.Response) : an unparsed response from requests
    reason                 (str) : a message to print to the user for fail.
    """
    message = "%s: %s: %s\n %s" % (
        reason,
        response.status_code,
        response.reason,
        response.json(),
    )

    if os.environ.get("PASS_ON_ERROR"):
        print("Error, but PASS_ON_ERROR is set, continuing: %s" % message)
    else:
        sys.exit(message)


def parse_into_list(values):
    """A list of reviewers or assignees to parse from a string to a list

    Parameters:
    values (str) : a list of space separated, quoted values to parse to a list
    """
    if values:
        values = values.replace('"', "").replace("'", "")
    if not values:
        return []
    return [x.strip() for x in values.split(" ")]


def set_env(name, value):
    """helper function to echo a key/value pair to the environement file

    Parameters:
    name (str)  : the name of the environment variable
    value (str) : the value to write to file
    """
    environment_file_path = os.environ.get("GITHUB_ENV")

    with open(environment_file_path, "a") as environment_file:
        environment_file.write("%s=%s" % (name, value))


def open_pull_request(title, body, target, source, is_draft=False, can_modify=True):
    """Open pull request opens a pull request with a given body and content,
    and sets output variables. An unparsed response is returned.

    Parameters:
    title       (str) : the title to set for the new pull request
    body        (str) : the body to set for the new pull request
    target      (str) : the target branch
    source      (str) : the source branch
    is_draft   (bool) : indicate the pull request is a draft
    can_modify (bool) : indicate the maintainer can modify
    """
    print("No pull request from %s to %s is open, continuing!" % (source, target))

    # Post the pull request
    data = {
        "title": title,
        "body": body,
        "base": target,
        "head": source,
        "draft": is_draft,
        "maintainer_can_modify": can_modify,
    }
    print("Data for opening pull request: %s" % data)
    response = requests.post(PULLS_URL, json=data, headers=HEADERS)
    if response.status_code != 201:
        abort_if_fail(response, "Unable to create pull request")

    return response


def update_pull_request(entry, title, body, target, can_modify=True, state=None):
    """Given an existing pull request, update it.

    Parameters:
    entry      (dict) : the pull request metadata
    title       (str) : the title to set for the new pull request
    body        (str) : the body to set for the new pull request
    target      (str) : the target branch
    state      (bool) : the state of the PR (open, closed)
    can_modify (bool) : indicate the maintainer can modify
    """
    print("PULL_REQUEST_UPDATE is set, updating existing pull request.")

    data = {
        "title": title,
        "body": body,
        "base": target,
        "state": state or "open",
        "maintainer_can_modify": can_modify,
    }
    # PATCH /repos/{owner}/{repo}/pulls/{pull_number}
    url = "%s/%s" % (PULLS_URL, entry.get("number"))
    print("Data for updating pull request: %s" % data)
    response = requests.patch(url, json=data, headers=HEADERS)
    if response.status_code != 201:
        abort_if_fail(response, "Unable to create pull request")

    return response


def set_pull_request_groups(response):
    """Given a response for an open or updated PR, set metadata

    Parameters:
    response (requests.Response) : a requests response, unparsed
    """
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
    set_env("PULL_REQUEST_NUMBER", number)
    print("::set-output name=pull_request_number::%s" % number)
    set_env("PULL_REQUEST_RETURN_CODE", pull_request_return_code)
    print("::set-output name=pull_request_return_code::%s" % pull_request_return_code)
    set_env("PULL_REQUEST_URL", html_url)
    print("::set-output name=pull_request_url::%s" % html_url)


def list_pull_requests(target, source):
    """Given a target and source, return a list of pull requests that match
    (or simply exit given some kind of error code)

    Parameters:
    target (str) : the target branch
    source (str) : the source branch
    """
    # Check if the branch already has a pull request open
    params = {"base": target, "head": source, "state": "open"}
    print("Params for checking if pull request exists: %s" % params)
    response = requests.get(PULLS_URL, params=params)

    # Case 1: 404 might warrant needing a token
    if response.status_code == 404:
        response = requests.get(PULLS_URL, params=params, headers=HEADERS)
    if response.status_code != 200:
        abort_if_fail(response, "Unable to retrieve information about pull requests")

    return response.json()


def add_assignees(entry):
    """Given a pull request metadata (from create or update) add assignees

    Parameters:
    entry (dict) : the pull request metadata
    """
    # Remove leading and trailing quotes
    assignees = parse_into_list(assignees)
    number = entry.get("number")

    print(
        "Attempting to assign %s to pull request with number %s" % (assignees, number)
    )

    # POST /repos/:owner/:repo/issues/:issue_number/assignees
    data = {"assignees": assignees}
    ASSIGNEES_URL = "%s/%s/assignees" % (ISSUE_URL, number)
    response = requests.post(ASSIGNEES_URL, json=data, headers=HEADERS)
    if response.status_code != 201:
        abort_if_fail(response, "Unable to create assignees")

    assignees_return_code = 0 if response.status_code == 201 else response.status_code
    print("::group::github assignees response")
    print(response.json())
    print("::endgroup::github assignees response")
    set_env("ASSIGNEES_RETURN_CODE", assignees_return_code)
    print("::set-output name=assignees_return_code::%s" % assignees_return_code)


def find_pull_request(listing, source):
    """Given a listing and a source, find a pull request based on the source
    (the branch name).

    Parameters:
    listing (list) : the list of PR objects (dict) to parse over
    source   (str) : the source (head) branch to look for
    """
    if listing:
        for entry in listing:
            if entry.get("head", {}).get("ref", "") == source:
                print("Pull request from %s to %s is already open!" % (source, target))
                return entry


def add_reviewers(entry, reviewers, team_reviewers):
    """Given regular or team reviewers, add them to a PR.

    Parameters:
    entry (dict) : the pull request metadata
    """
    print("Found reviewers: %s and team reviewers: %s" % (reviewers, team_reviewers))
    team_reviewers = parse_into_list(team_reviewers)
    reviewers = parse_into_list(reviewers)
    print("Parsed reviewers: %s and team reviewers: %s" % (reviewers, team_reviewers))

    # POST /repos/:owner/:repo/pulls/:pull_number/requested_reviewers
    REVIEWERS_URL = "%s/%s/requested_reviewers" % (PULLS_URL, entry.get("number"))

    data = {"reviewers": reviewers, "team_reviewers": team_reviewers}
    response = requests.post(REVIEWERS_URL, json=data, headers=HEADERS)
    if response.status_code != 201:
        abort_if_fail(response, "Unable to assign reviewers")
    reviewers_return_code = 0 if response.status_code == 201 else response.status_code

    print("::group::github reviewers response")
    print(response.json())
    print("::endgroup::github reviewers response")
    set_env("REVIEWERS_RETURN_CODE", reviewers_return_code)
    print("::set-output name=reviewers_return_code::%s" % reviewers_return_code)
    print("Add reviewers return code: %s" % reviewers_return_code)


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
    state="open",
):
    """Create pull request is the base function that determines if the PR exists,
    and then updates or creates it depending on user preferences.
    """
    listing = list_pull_requests(target, source)

    # Determine if the pull request is already open
    entry = find_pull_request(listing, source)
    response = None

    # Case 1: we found the PR, the user wants to pass
    if entry and os.environ.get("PASS_IF_EXISTS"):
        print("PASS_IF_EXISTS is set, exiting with success status.")
        sys.exit(0)

    # Does the user want to update the existing PR?
    if entry and os.environ.get("PULL_REQUEST_UPDATE"):
        response = update_pull_request(entry, title, body, target, can_modify, state)
        set_pull_request_groups(response)

    # If it's not open, we open a new pull request
    elif not entry:
        response = open_pull_request(title, body, target, source, is_draft, can_modify)
        set_pull_request_groups(response)

    # If we have a response, parse into json (no longer need retvals)
    response = response.json() if response else None

    # If we have opened or updated, we can add assignees
    if response and assignees:
        add_assignees(response)
    if response and (reviewers or team_reviewers):
        add_reviewers(response, reviewers, team_reviewers)


def main():
    """main primarily parses environment variables to prepare for creation"""

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
        print("PULL_REQUEST_DRAFT set to a value: created PRs will be draft PRs.")
        pull_request_draft = True

    # If an update is true, we can change the state
    pull_request_state = os.environ.get("PULL_REQUEST_STATE", "open")
    if pull_request_state not in ["open", "closed"]:
        sys.exit("State is required to be one of 'open' or 'closed'")

    # Maintainer can modify, defaults to CAN, unless user sets MAINTAINER_CANT_MODIFY
    maintainer_can_modify = os.environ.get("MAINTAINER_CANT_MODIFY")
    if not maintainer_can_modify:
        print("No preference for maintainer being able to modify: default is true.")
        maintainer_can_modify = True
    else:
        print(
            "MAINTAINER_CANT_MODIFY set to a value: maintainer will not be able to modify."
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
    from_branch = os.environ.get("PULL_REQUEST_FROM_BRANCH")
    if not from_branch:
        print("PULL_REQUEST_FROM_BRANCH is not set, checking branch in payload.")
        with open(check_events_json(), "r") as fd:
            from_branch = json.loads(fd.read()).get("ref")
        from_branch = from_branch.replace("refs/heads/", "").strip("/")
    else:
        print("PULL_REQUEST_FROM_BRANCH is set.")

    # At this point, we must have a branch
    if from_branch:
        print("Found branch %s to open PR from" % from_branch)
    else:
        sys.exit(
            "You are required to define PULL_REQUEST_FROM_BRANCH in the environment."
        )

    # If it's to the target branch, ignore it
    if from_branch == pull_request_branch:
        print("Target and current branch are identical (%s), skipping." % from_branch)
        sys.exit(0)

    # If the prefix for the branch matches
    if not branch_prefix or from_branch.startswith(branch_prefix):

        # Pull request body (optional)
        pull_request_body = os.environ.get(
            "PULL_REQUEST_BODY",
            "This is an automated pull request to update from branch %s" % from_branch,
        )

        print("::group::pull request body")
        print(pull_request_body)
        print("::endgroup::pull request body")

        # Pull request title (optional)
        pull_request_title = os.environ.get(
            "PULL_REQUEST_TITLE", "Update from %s" % from_branch
        )
        print("::group::pull request title")
        print(pull_request_title)
        print("::endgroup::pull request title")

        # Create the pull request
        create_pull_request(
            target=pull_request_branch,
            source=from_branch,
            body=pull_request_body,
            title=pull_request_title,
            is_draft=pull_request_draft,
            can_modify=maintainer_can_modify,
            assignees=assignees,
            reviewers=reviewers,
            team_reviewers=team_reviewers,
            state=pull_request_state,
        )


if __name__ == "__main__":
    print("==========================================================================")
    print("START: Running Pull Request on Branch Update Action!")
    main()
    print("==========================================================================")
    print("END: Finished")
