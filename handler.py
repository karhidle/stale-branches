import logging
import os
import re

from github import Github, GithubException
from jira import JIRA
from jira import exceptions as jira_exceptions

# env variables
jira_url = os.getenv('jira_url')
jira_key_cert_file_path = os.getenv('jira_key_cert_file_path')
jira_access_token = os.getenv('jira_access_token')
jira_access_token_secret = os.getenv('jira_access_token_secret')
jira_consumer_key = os.getenv('jira_consumer_key')
jira_statuses = os.getenv('jira_statuses')

github_access_token = os.getenv('github_access_token')
repository_names = os.getenv('repository_names')
# end env variables

# Jira authentication setup
jira_key_cert_data = None
with open(jira_key_cert_file_path, 'r') as jira_key_cert_file:
    jira_key_cert_data = jira_key_cert_file.read()

jira_oauth_dict = {
    'access_token': jira_access_token,
    'access_token_secret': jira_access_token_secret,
    'consumer_key': jira_consumer_key,
    'key_cert': jira_key_cert_data
}
auth_jira = JIRA(jira_url, oauth=jira_oauth_dict)

# Github authentication setup
g = Github(github_access_token)

# Look for stale branches for all the specified repos
total_stale_branches = 0
general_report = ''
for repo_name in repository_names:

    logging.debug(f'\nChecking repo: {repo_name}')
    repo = g.get_repo(f'teamexos/{repo_name}')
    repo_report = ''

    # confirm the name for the main develop branch
    main_develop_branch = 'develop'
    try:
        develop_branch = repo.get_branch('develop')
    except GithubException:
        main_develop_branch = 'master'
        logging.debug('Develop branch not found, using master as the main develop branch.')
        continue

    branches = repo.get_branches()
    for branch in branches:
        # only check feature branches
        if not branch.name.startswith('feature/'):
            continue

        # compare the branch against the main develop branch
        comparison = repo.compare(main_develop_branch, branch.name)

        if comparison.behind_by == 0:
            # the branch is up to date, nothing to do
            continue

        # try to get the jira ticket number from the branch name
        ticket = None
        result = re.search(r'feature/(?P<ticket>[a-zA-Z]+-[0-9]+).*', branch.name)
        if result:
            ticket = result.groupdict()['ticket'].upper()
            try:
                issue = auth_jira.issue(ticket)
            except jira_exceptions.JIRAError:
                logging.debug(f"The ticket {ticket} specified in the branch name doesn't exist in Jira.")

            if issue and issue.fields.status.name not in jira_statuses:
                continue

        author = branch.commit.author.login if branch.commit.author else 'Unknown'
        repo_report += f'\nBranch: {branch.name}, comparison status: {comparison.status}, author: {author}'
        if ticket:
            repo_report += f', ticket status: "{issue.fields.status.name}'

        total_stale_branches += 1

    if repo_report:
        general_report += f'Repo: {repo_name}, develop branch name: {main_develop_branch}{repo_report}\n\n'

general_report = f'Total stale branches: {total_stale_branches}\n\n{general_report}'
print(general_report)
