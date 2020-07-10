#!/bin/bash

# Suggested by Github actions to be strict
set -e
set -o pipefail

################################################################################
# Global Variables (we can't use GITHUB_ prefix)
################################################################################

API_VERSION=v3
BASE=https://api.github.com
AUTH_HEADER="Authorization: token ${GITHUB_TOKEN}"
HEADER="Accept: application/vnd.github.${API_VERSION}+json"
HEADER="${HEADER}; application/vnd.github.antiope-preview+json; application/vnd.github.shadow-cat-preview+json"

# URLs
REPO_URL="${BASE}/repos/${GITHUB_REPOSITORY}"
ISSUE_URL=${REPO_URL}/issues
PULLS_URL=$REPO_URL/pulls

################################################################################
# Helper Functions
################################################################################


check_credentials() {

    if [[ -z "${GITHUB_TOKEN}" ]]; then
        printf "You must include the GITHUB_TOKEN as an environment variable.\n"
        exit 1
    fi

}

check_events_json() {

    if [[ ! -f "${GITHUB_EVENT_PATH}" ]]; then
        printf "Cannot find Github events file at ${GITHUB_EVENT_PATH}\n";
        exit 1
    fi
    printf "Found ${GITHUB_EVENT_PATH}\n";

}

create_pull_request() {

    # JSON strings
    SOURCE="$(echo -n "${1}" | jq --raw-input --slurp ".")"  # from this branch
    TARGET="$(echo -n "${2}" | jq --raw-input --slurp ".")"  # pull request TO this target
    BODY="$(echo -n "${3}" | jq --raw-input --slurp ".")"    # this is the content of the message
    TITLE="$(echo -n "${4}" | jq --raw-input --slurp ".")"   # pull request title
    DRAFT="${5}"                                             # pull request draft?
    MODIFY="${6}"                                            # maintainer can modify
    ASSIGNEES="$(echo -n "${7}" | jq --raw-input --slurp ".")"
    REVIEWERS="$(echo -n "${8}" | jq --raw-input --slurp ".")"
    TEAM_REVIEWERS="$(echo -n "${9}" | jq --raw-input --slurp ".")"

    # Do we want a different username for GitHub actor?
    ACTOR="${GITHUB_ACTOR}"
    if [ ! -z "${PULL_REQUEST_ACTOR}" ]; then
        ACTOR="${PULL_REQUEST_ACTOR}"
    fi

    # Check if the branch already has a pull request open
    DATA="{\"base\":${TARGET}, \"head\":${SOURCE}, \"body\":${BODY}}"
    RESPONSE=$(curl -sSL -H "${AUTH_HEADER}" -H "${HEADER}" --user "${ACTOR}" -X GET --data "${DATA}" ${PULLS_URL})
    PR=$(echo "${RESPONSE}" | jq --raw-output '.[] | .head.ref')
    printf "Response ref: ${PR}\n"

    # Option 1: The pull request is already open
    if [[ "${PR}" == "${SOURCE}" ]]; then
        printf "Pull request from ${SOURCE} to ${TARGET} is already open!\n"

    # Option 2: Open a new pull request
    else
        # Post the pull request
        DATA="{\"title\":${TITLE}, \"body\":${BODY}, \"base\":${TARGET}, \"head\":${SOURCE}, \"draft\":${DRAFT}, \"maintainer_can_modify\":${MODIFY}}"
        printf "curl --user ${ACTOR} -X POST --data ${DATA} ${PULLS_URL}\n"
        RESPONSE=$(curl -sSL -H "${AUTH_HEADER}" -H "${HEADER}" --user "${ACTOR}" -X POST --data "${DATA}" ${PULLS_URL})
        RETVAL=$?
        printf "Pull request return code: ${RETVAL}\n"

        # if we were successful to open, add assignees and reviewers
        if [[ "${RETVAL}" == "0" ]]; then

            echo "${RESPONSE}"

            NUMBER=$(echo "${RESPONSE}" | jq --raw-output '.number')
            printf "Number opened for PR is ${NUMBER}\n"
            HTML_URL=$(echo "${RESPONSE}" | jq --raw-output '.html_url')

            echo ::set-env name=PULL_REQUEST_NUMBER::${NUMBER}
            echo ::set-output name=pull_request_number::${NUMBER}
            echo ::set-env name=PULL_REQUEST_RETURN_CODE::${RETVAL}
            echo ::set-output name=pull_request_return_code::${RETVAL}
            echo ::set-env name=PULL_REQUEST_URL::${HTML_URL}
            echo ::set-output name=pull_request_url::${HTML_URL}

            # Assignees are defined
            if [[ "$ASSIGNEES" != '""' ]]; then

                # Remove leading and trailing quotes
                ASSIGNEES=$(echo "$ASSIGNEES" | sed -e 's/^"//' -e 's/"$//')

                # Parse assignees into a list            
                ASSIGNEES=$(echo $ASSIGNEES | printf '"%s"\n' $ASSIGNEES|paste -sd, -)
                printf "Attempting to assign ${ASSIGNEES} to ${PR} with number ${NUMBER}"

                # POST /repos/:owner/:repo/issues/:issue_number/assignees
                DATA="{\"assignees\":[${ASSIGNEES}]}"
                echo "${DATA}"
                ASSIGNEES_URL="${ISSUE_URL}/${NUMBER}/assignees"
                curl -sSL -H "${AUTH_HEADER}" -H "${HEADER}" --user "${ACTOR}" -X POST --data "${DATA}" ${ASSIGNEES_URL}
                RETVAL=$?
                printf "Add assignees return code: ${RETVAL}\n"
                echo ::set-env name=ASSIGNEES_RETURN_CODE::${RETVAL}
                echo ::set-output name=assignees_return_code::${RETVAL}

            fi

            # Reviewers or team reviewers are defined
            if [[ "$REVIEWERS" != '""' ]] || [[ "$TEAM_REVIEWERS" != '""' ]]; then

                printf "Found reviewers: ${REVIEWERS} and team reviewers: ${TEAM_REVIEWERS}\n"

                REVIEWERS=$(echo "$REVIEWERS" | sed -e 's/^"//' -e 's/"$//')
                REVIEWERS=$(echo $REVIEWERS | printf '"%s"\n' $REVIEWERS|paste -sd, -)
                TEAM_REVIEWERS=$(echo "$TEAM_REVIEWERS" | sed -e 's/^"//' -e 's/"$//')
                TEAM_REVIEWERS=$(echo $TEAM_REVIEWERS | printf '"%s"\n' $TEAM_REVIEWERS|paste -sd, -)

                # If either is empty, don't include emty string (provide empty list)
                if [[ "$REVIEWERS" == '""' ]]; then REVIEWERS=; fi
                if [[ "$TEAM_REVIEWERS" == '""' ]]; then TEAM_REVIEWERS=; fi

                # POST /repos/:owner/:repo/pulls/:pull_number/requested_reviewers
                REVIEWERS_URL="${PULLS_URL}/${NUMBER}/requested_reviewers"
                DATA="{\"reviewers\":[${REVIEWERS}], \"team_reviewers\":[${TEAM_REVIEWERS}]}"
                echo "${DATA}"
                curl -sSL -H "${AUTH_HEADER}" -H "${HEADER}" --user "${ACTOR}" -X POST --data "${DATA}" ${REVIEWERS_URL}

                RETVAL=$?
                printf "Add reviewers return code: ${RETVAL}\n"
                echo ::set-env name=REVIEWERS_RETURN_CODE::${RETVAL}
                echo ::set-output name=reviewers_return_code::${RETVAL}

            fi
        fi
    fi
}


main () {

    # path to file that contains the POST response of the event
    # Example: https://github.com/actions/bin/tree/master/debug
    # Value: /github/workflow/event.json
    check_events_json;

    # User specified branch to PR to, and check
    if [ -z "${BRANCH_PREFIX}" ]; then
        printf "No branch prefix is set, all branches will be used.\n"
        BRANCH_PREFIX=""
        printf "Branch prefix is $BRANCH_PREFIX\n"
    fi

    if [ -z "${PULL_REQUEST_BRANCH}" ]; then
        PULL_REQUEST_BRANCH=master
    fi
    printf "Pull requests will go to ${PULL_REQUEST_BRANCH}\n"

    # Pull request draft
    if [ -z "${PULL_REQUEST_DRAFT}" ]; then
        printf "No explicit preference for draft PR: created PRs will be normal PRs.\n"
        PULL_REQUEST_DRAFT="false"
    else
        printf "Environment variable PULL_REQUEST_DRAFT set to a value: created PRs will be draft PRs.\n"
        PULL_REQUEST_DRAFT="true"
    fi

    # Maintainer can modify, defaults to CAN, unless user sets MAINTAINER_CANT_MODIFY
    if [ -z "${MAINTAINER_CANT_MODIFY}" ]; then
        printf "No explicit preference for maintainer being able to modify: default is true.\n"
        MODIFY="true"
    else
        printf "Environment variable MAINTAINER_CANT_MODIFY set to a value: maintainer will not be able to modify.\n"
        MODIFY="false"
    fi

    # Assignees
    ASSIGNEES=""
    if [ -z "${PULL_REQUEST_ASSIGNEES}" ]; then
        printf "PULL_REQUEST_ASSIGNEES is not set, no assignees.\n"
    else
        printf "PULL_REQUEST_ASSIGNEES is set, ${PULL_REQUEST_ASSIGNEES}\n"
        ASSIGNEES="${PULL_REQUEST_ASSIGNEES}"
    fi

    # Reviewers (individual and team)
    TEAM_REVIEWERS=""
    REVIEWERS=""
    if [ -z "${PULL_REQUEST_REVIEWERS}" ]; then
        printf "PULL_REQUEST_REVIEWERS is not set, no reviewers.\n"
    else
        printf "PULL_REQUEST_REVIEWERS is set, ${PULL_REQUEST_REVIEWERS}\n"
        REVIEWERS="${PULL_REQUEST_REVIEWERS}"
    fi
    if [ -z "${PULL_REQUEST_TEAM_REVIEWERS}" ]; then
        printf "PULL_REQUEST_TEAM_REVIEWERS is not set, no team reviewers.\n"
    else
        printf "PULL_REQUEST_TEAM_REVIEWERS is set, ${PULL_REQUEST_TEAM_REVIEWERS}\n"
        TEAM_REVIEWERS="${PULL_REQUEST_TEAM_REVIEWERS}"
    fi
    
    # The user is allowed to explicitly set the name of the branch
    if [ -z "${PULL_REQUEST_FROM_BRANCH}" ]; then
        printf "PULL_REQUEST_FROM_BRANCH is not set, checking branch in payload.\n"
        BRANCH=$(jq --raw-output .ref "${GITHUB_EVENT_PATH}");
        BRANCH=$(echo "${BRANCH/refs\/heads\//}")
    else
        printf "PULL_REQUEST_FROM_BRANCH is set.\n"
        BRANCH="${PULL_REQUEST_FROM_BRANCH}"        
    fi

    # At this point, we must have a branch
    if [[ "$BRANCH" != "null" ]]; then
        printf "Found branch $BRANCH to open PR from\n"
    else
        printf "No branch in payload, you are required to define PULL_REQUEST_FROM_BRANCH in the environment.\n"
        exit 1
    fi

    # If it's to the target branch, ignore it
    if [[ "${BRANCH}" == "${PULL_REQUEST_BRANCH}" ]]; then
        printf "Target and current branch are identical (${BRANCH}), skipping.\n"
    else

        # If the prefix for the branch matches
        if  [[ $BRANCH == ${BRANCH_PREFIX}* ]]; then

            # Ensure we have a GitHub token
            check_credentials

            # Pull request body (optional)
            if [ -z "${PULL_REQUEST_BODY}" ]; then
                echo "No pull request body is set, will use default."
                PULL_REQUEST_BODY="This is an automated pull request to update from branch ${BRANCH}"
            fi
            printf "Pull request body is ${PULL_REQUEST_BODY}\n"

            # Pull request title (optional)
            if [ -z "${PULL_REQUEST_TITLE}" ]; then
                printf "No pull request title is set, will use default.\n"
                PULL_REQUEST_TITLE="Update from ${BRANCH}"
            fi
            printf "Pull request title is ${PULL_REQUEST_TITLE}\n"

            create_pull_request "${BRANCH}" "${PULL_REQUEST_BRANCH}" "${PULL_REQUEST_BODY}" \
                                "${PULL_REQUEST_TITLE}" "${PULL_REQUEST_DRAFT}" "${MODIFY}" \
                                "${ASSIGNEES}" "${REVIEWERS}" "${TEAM_REVIEWERS}"

        fi

    fi
}

echo "==========================================================================
START: Running Pull Request on Branch Update Action!";
main;
echo "==========================================================================
END: Finished";
