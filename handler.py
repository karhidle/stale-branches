import logging
import operator
import os
import re
from collections import defaultdict

from github import Github, GithubException
from jira import JIRA
from jira import exceptions as jira_exceptions

# env variables
jira_url = os.environ.get('JIRA_URL')
jira_key_cert_file_path = os.environ.get('JIRA_KEY_CERT_FILE_PATH')
jira_access_token = os.environ.get('JIRA_ACCESS_TOKEN')
jira_access_token_secret = os.environ.get('JIRA_ACCESS_TOKEN_SECRET')
jira_consumer_key = os.environ.get('JIRA_CONSUMER_KEY')
jira_statuses_for_task_completion = os.environ.get('JIRA_STATUSES_FOR_TASK_COMPLETION')

github_access_token = os.environ.get('GITHUB_ACCESS_TOKEN')
github_account = os.environ.get('GITHUB_ACCOUNT')
github_repository_names = os.environ.get('REPOSITORY_LIST')
# end env variables

if not (jira_url and
        jira_key_cert_file_path and
        jira_access_token and
        jira_access_token_secret and
        jira_consumer_key and
        github_access_token and
        github_account and
        github_repository_names):
    logging.error('There are missing parameters, please check your environment variable setup.')
    exit(1)

jira_statuses_for_task_completion = jira_statuses_for_task_completion.split(',') \
    if jira_statuses_for_task_completion else ('Resolved', 'Closed')

github_repository_names = github_repository_names.split(',')

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
author_count = defaultdict(int)

for repo_name in github_repository_names:
    logging.debug(f'\nChecking repo: {repo_name}')

    try:
        repo = g.get_repo(f'{github_account}/{repo_name}')
    except GithubException:
        logging.error(f'Github repository "{github_account}/{repo_name}" not found!')
        continue

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
        # only check feature and hotfix branches
        if not branch.name.startswith('feature/') and not branch.name.startswith('hotfix/'):
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

            if issue and issue.fields.status.name not in jira_statuses_for_task_completion:
                # the issue hasn't been marked as resolved in jira, so the branch may still be needed
                continue

        author = branch.commit.author.login if branch.commit.author else 'Unknown'
        author_count[author] += 1
        repo_report += f'\nBranch: {branch.name}, comparison status: {comparison.status}, author: {author}'
        if ticket:
            repo_report += f', ticket status: "{issue.fields.status.name}'

        total_stale_branches += 1

    if repo_report:
        general_report += f'Repo: {repo_name}, develop branch name: {main_develop_branch}{repo_report}\n\n'

general_report = f'Total stale branches: {total_stale_branches}\n\n{general_report}\nCount by author:\n\n'
for author, count in sorted(author_count.items(), key=operator.itemgetter(1), reverse=True):
    general_report += f'{author}: {count}\n'

print(general_report)
