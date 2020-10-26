import fb_group_data.fb_api_request_urls as fb_api
import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render

message_element = {
    'title': '',
    'image_url': 'https://i.ibb.co/5M7GTR5/Screen-Shot-2020-10-26-at-2-14-27.png',
    'default_action': {
        'type': 'web_url',
        'url': ''
    }
}

message_gallery = {
    'messages': [{
        'attachment': {
            'type': 'template',
            'payload': {
                'template_type': 'generic',
                'image_aspect_ratio': 'square',
                'elements': []
            },
        }
    }]
}


def fb_login_redirect(request):
    """
    Process the response from the FB Login, checks the state and error fields,
    if no errors were found, it uses the code from the response to request an auth token.
    Adds the auth token to the session.

    :param request: Django request object
    :return: Redirect to Home page to execute token validation if success, otherwise Error view (#todo)
    """
    # Check existing sessions
    # return HttpResponse(str(request))
    saved_token = request.session.get(fb_api.KEY_FB_AUTH_TOKEN, None)

    if not fb_api.validate_auth_token(request, saved_token):
        return HttpResponse("Error validating token")

    # Validate CSRF and check if there was an error
    state = request.GET['state']
    # TODO Pretty error pages
    if not state == settings.FB_LOGIN_STATE_PARAM:
        return 'CSRF Error'
    if 'error' in request.GET:
        error = request.GET['error']
        return f'Login Error: {error}'

    # Parse auth response
    auth_code = request.GET['code']
    auth_token_request = requests.get(fb_api.build_auth_token_url(auth_code))
    # print(auth_token_request)
    token_response = auth_token_request.json()

    # TODO Validate permissions
    # https://developers.facebook.com/docs/facebook-login/manually-build-a-login-flow#permscheck

    # Save token in session and redirect to main page
    # TODO handle error in token_response
    # return HttpResponse(str(token_response))
    request.session[fb_api.KEY_FB_AUTH_TOKEN] = token_response['access_token']

    return redirect('fb:home')


#
# VIEWS TO SHOW DATA REPORTS
#

# @login_required(login_url=reverse('fb:log_in'))
@login_required(login_url=settings.FB_LOGIN_URL)
def home(request):
    """
    Shows a view that allows the user to select the FB group to analyze

    :param request: Django request object
    :return: Home page view or redirects to FB login
    """
    # Retrieve user groups
    # TODO Handle pagination
    user_managed_groups = get_managed_groups(request)

    context = {'groups': user_managed_groups}
    return render(request, 'fb_data_miner/groups.html', context)


def get_managed_groups(request):
    user_managed_groups = []
    auth_token = request.session[fb_api.KEY_FB_AUTH_TOKEN]

    user_groups_url = fb_api.build_user_groups_url(request.user.fbprofile.fb_id, auth_token)
    while True:
        user_groups_response = requests.get(user_groups_url)
        user_groups_dict = user_groups_response.json()
        if not group_request_has_data(user_groups_dict):
            print('no data')
            break
        user_groups = user_groups_dict["data"]
        print(f'groups: {len(user_groups)}')
        print(f'groups data: {user_groups}')
        managed_groups = list(filter(lambda g: g['administrator'], user_groups))
        print(f'managed_groups: {len(managed_groups)}')
        user_managed_groups.extend(managed_groups)

        if not group_request_has_next(user_groups_dict):
            print('no next')
            break

        user_groups_url = user_groups_dict['paging']['next']

    return user_managed_groups


@login_required(login_url=settings.FB_LOGIN_URL)
def group(request, group_id):
    """
    Shows a view with a menu of various group analysis options.

    :param request: Django request object
    :param group_id: id of the group to analyze
    :return: View that shows various group analysis options
    """
    auth_token = request.session[fb_api.KEY_FB_AUTH_TOKEN]
    group_details = requests.get(fb_api.build_group_details_url(group_id, auth_token))

    context = {
        'group_name': group_details.json()['name'],
        'group_id': group_id
    }

    return render(request, 'fb_data_miner/group_detail.html', context)


@login_required(login_url=settings.FB_LOGIN_URL)
def group_weekly_summary(request, group_id, group_name, resp_format='html'):
    """
    Shows weekly summary of the group, meaning the top posts (also users and topics?)
    from that week, with a default start day of Monday

    :param request: Django request object
    :param group_id: id of the group to get the summary
    :param group_name: name of the selected group
    :param resp_format: format of the reponse, html or json
    :return: View that shows a weekly summary of a group identified by group_id
    """
    auth_token = request.session[fb_api.KEY_FB_AUTH_TOKEN]
    group_feed_request_url = fb_api.build_group_feed_url(group_id, auth_token, fb_api.SummaryPeriod.CurrentWeek)
    print(group_feed_request_url)

    group_feed = get_all_group_post_from_period(group_feed_request_url)
    group_feed = list(filter(
        lambda x: (x.get('shares', {'count': 0})['count'] > 0 or len(x.get('comments', {'data': []})['data']) > 0),
        group_feed))[:5]
    group_feed.sort(key=lambda x: x.get('shares', {'count': 0})['count'] + len(x.get('comments', {'data': []})['data']),
                    reverse=True)
    total_comments, top_commented_post, total_shares, top_shared_post = parse_feed_info(group_feed)

    if resp_format == 'html':
        context = {
            'group_name': group_name,
            'group_feed': group_feed,
            'total_comments': total_comments,
            'top_commented_post': top_commented_post,
            'total_shares': total_shares,
            'top_shared_post': top_shared_post,
        }
        return render(request, 'fb_data_miner/group_weekly_summary.html', context)
    else:
        for post in group_feed:
            message = message_element.copy()
            message['title'] = post['message']
            message['default_action']['url'] = post['permalink_url']
            message_gallery['messages'][0]['attachment']['payload']['elements'].append(message)
        return JsonResponse(message_gallery)


def get_all_group_post_from_period(group_feed_request_url):
    group_feed = []
    request_count = 0
    while True:
        request_count += 1
        print(f'request: {request_count}')
        group_feed_response = requests.get(group_feed_request_url)
        group_feed_dict = group_feed_response.json()
        if not group_request_has_data(group_feed_dict):
            print('no data')
            break
        print(f'posts: {len(group_feed_dict["data"])}')
        group_feed.extend(group_feed_dict['data'])

        if not group_request_has_next(group_feed_dict):
            print('no next')
            break

        group_feed_request_url = group_feed_dict['paging']['next']

    print(f'total requests: {request_count}')
    return group_feed


# TODO Create data model class for parsed info to avoid handle single variables
def parse_feed_info(group_feed):
    total_comments = 0
    top_commented_post = None
    total_shares = 0
    top_shared_post = None
    print(f'posts in group_feed: {group_feed}')
    for post in group_feed:
        total_comments, top_commented_post = get_post_comments_info(post, total_comments, top_commented_post)
        total_shares, top_shared_post = get_post_shares_info(post, total_shares, top_shared_post)

    return total_comments, top_commented_post, total_shares, top_shared_post


def get_post_comments_info(post, total_comments, top_commented_post):
    if 'comments' in post:
        post_comments = len(post['comments']['data'])
        total_comments += post_comments
        if not top_commented_post or post_comments > len(top_commented_post['comments']['data']):
            top_commented_post = post

    return total_comments, top_commented_post


def get_post_shares_info(post, total_shares, top_shared_post):
    if 'shares' in post:
        post_shares = post['shares']['count']
        total_shares += post_shares
        if not top_shared_post or post_shares > top_shared_post['shares']['count']:
            top_shared_post = post

    return total_shares, top_shared_post


def group_request_has_data(group_feed_response):
    return 'data' in group_feed_response and len(group_feed_response['data']) > 0


def group_request_has_next(group_feed_response):
    return 'paging' in group_feed_response and 'next' in group_feed_response['paging']
