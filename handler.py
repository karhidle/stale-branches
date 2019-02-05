import boto3
import logging
import operator
import re
from collections import defaultdict

from github import Github, GithubException
from jira import JIRA
from jira import exceptions as jira_exceptions


# logging.getLogger().setLevel(logging.DEBUG)


def load_parameters(namespace: str, env: str) -> dict:
    """
    Load parameters from SSM Parameter Store.

    :namespace: The application namespace.
    :env: The current application environment.
    :return: The config loaded from Parameter Store.
    """
    params = {}
    path = f'/{namespace}/{env}'
    ssm = boto3.client('ssm')
    more = None
    args = {"Path": path, "Recursive": True, "WithDecryption": True}
    while more is not False:
        if more:
            args["NextToken"] = more
        params = ssm.get_parameters_by_path(**args)
        for param in params["Parameters"]:
            key = param["Name"].split("/")[3]
            params[key] = param["Value"]
        more = params.get("NextToken", False)
    return params


def stale_branches():
    """
    Create a report about stale branches for a list of repositories.

    """

    ssm_parameters = load_parameters('dev_tools', 'dev')

    print(ssm_parameters)

    jira_statuses_for_task_completion = ssm_parameters['jira_statuses_for_task_completion'].split(',') \
        if ssm_parameters['jira_statuses_for_task_completion'] else ('Resolved', 'Closed')

    print(ssm_parameters)
    repository_names = ssm_parameters['github_repository_names']
    print(repository_names)
    github_repository_names = repository_names.split(',')

    jira_oauth_dict = {
        'access_token': ssm_parameters['jira_access_token'],
        'access_token_secret': ssm_parameters['jira_access_token_secret'],
        'consumer_key': ssm_parameters['jira_consumer_key'],
        'key_cert': ssm_parameters['jira_private_key']
    }
    auth_jira = JIRA(ssm_parameters['jira_url'], oauth=jira_oauth_dict)

    # Github authentication setup
    g = Github(ssm_parameters['github_access_token'])

    # Look for stale branches for all the specified repos
    total_stale_branches = 0
    general_report = ''
    author_count = defaultdict(int)

    for repo_name in github_repository_names:
        logging.debug(f'\nChecking repo: {repo_name}')

        try:
            repo = g.get_repo(f"{ssm_parameters['github_account']}/{repo_name}")
        except GithubException:
            logging.error(f"Github repository '{ssm_parameters['github_account']}/{repo_name}' not found!")
            continue

        repo_report = ''

        # confirm the name for the main develop branch
        main_develop_branch = 'develop'
        try:
            _ = repo.get_branch('develop')
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
            repo_report += f'Branch: {branch.name}\nComparison status: {comparison.status}\nAuthor: {author}\n'
            if ticket:
                repo_report += f'Ticket status: "{issue.fields.status.name}\n\n'

            total_stale_branches += 1

        if repo_report:
            general_report += f'Repo: {repo_name}, develop branch name: {main_develop_branch}{repo_report}'

    count_by_author = ''
    for author, count in sorted(author_count.items(), key=operator.itemgetter(1), reverse=True):
        count_by_author += f'{author}: {count}\n'

    general_report = f'Total stale branches: {total_stale_branches}\n\n'\
                     f'Count by author:\n{count_by_author}\n'\
                     f'Summary:\n\n{general_report}'
    print(general_report)


stale_branches()
