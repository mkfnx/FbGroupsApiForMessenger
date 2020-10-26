import enum
import os
from datetime import datetime, timedelta

import requests
from django.conf import settings
from django.contrib.auth import authenticate, login
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '../fbgroup_insights/.env'))

FB_APP_ID = os.getenv('FB_APP_ID')
FB_APP_SECRET = os.getenv('FB_APP_SECRET')
# TODO create a secure param and check if needs to be generated for each request
FB_LOGIN_STATE_PARAM = os.getenv('FB_LOGIN_STATE_PARAM')

# TODO get host name dynamically
HOST_NAME = 'http://localhost:8000/'
# HOST_NAME = 'https://7aa208403fd8.ngrok.io/'

GRAPH_API_VERSION = 'v8.0'
SCOPES = 'email,groups_access_member_info'

FB_LOGIN_REDIRECT_PATH = 'fb_login_redirect'
GRAPH_API_ACCESS_TOKEN_PATH = 'oauth/access_token'
FB_LOGIN_REDIRECT_URI = f'{HOST_NAME}' + FB_LOGIN_REDIRECT_PATH
FB_AUTH_PARAMS = f'client_id={FB_APP_ID}&redirect_uri={FB_LOGIN_REDIRECT_URI}'
GRAPH_API_BASE_URL = f'https://graph.facebook.com/{GRAPH_API_VERSION}'

FB_LOGIN_URL = f'https://www.facebook.com/{GRAPH_API_VERSION}/dialog/oauth?{FB_AUTH_PARAMS} \
&state={FB_LOGIN_STATE_PARAM}&scope=groups_show_list'
# FB_APP_ACCESS_TOKEN_URL = f'{GRAPH_API_BASE_URL}/{GRAPH_API_ACCESS_TOKEN_PATH}?client_id={FB_APP_ID} \
# &client_secret={FB_APP_SECRET}&grant_type=client_credentials'
FB_APP_ACCESS_TOKEN_URL = f'{GRAPH_API_BASE_URL}/{GRAPH_API_ACCESS_TOKEN_PATH}?client_id={FB_APP_ID} \
&grant_type=client_credentials'

USER_GROUPS_FIELDS = 'fields=id,name,administrator'

GROUP_FEED_FIELDS = 'fields=link,message,created_time,updated_time,caption,description,from,message_tags,name,' \
                    'permalink_url,shares,status_type,type,comments,reactions'

# Key names for Session
KEY_FB_AUTH_TOKEN = 'fb_auth_token'
KEY_FB_APP_TOKEN = 'fb_app_token'
KEY_FB_USER_ID = 'fb_user_id'


# For now, just comparing hardcoded state
# TODO Check if better validation is needed
def is_state_valid(state):
    return state == FB_LOGIN_STATE_PARAM


#
# URL building functions
#
def build_auth_token_url(fb_auth_code):
    # FB_AUTH_TOKEN_URL
    auth_token_url = f'{GRAPH_API_BASE_URL}/{GRAPH_API_ACCESS_TOKEN_PATH}' \
                     f'?{FB_AUTH_PARAMS}&client_secret={FB_APP_SECRET}&code={fb_auth_code}'
    # print(auth_token_url)
    return auth_token_url


def build_auth_token_debug_url(auth_token, app_token):
    # FB_AUTH_TOKEN_DEBUG_URL
    return f'{GRAPH_API_BASE_URL}/debug_token?input_token={auth_token}&access_token={app_token}'


def build_user_groups_url(user_id, auth_token):
    # FB_USER_GROUPS_URL
    user_groups_url = f'{GRAPH_API_BASE_URL}/{user_id}/groups?access_token={auth_token}&{USER_GROUPS_FIELDS}'
    print(user_groups_url)
    return user_groups_url


def build_group_details_url(group_id, auth_token):
    print(f'group_id: {group_id}')
    return f'{GRAPH_API_BASE_URL}/{group_id}?access_token={auth_token}'


def build_group_feed_url(group_id, auth_token, summary_period):
    url = f'{GRAPH_API_BASE_URL}/{group_id}/feed?access_token={auth_token}' \
          f'&{GROUP_FEED_FIELDS}' \
          f'&{build_time_paging_param(summary_period)}'
    return url


#
# FB Auth helper functions
#

# TODO Validate errors
# TODO Store credential in persistent storage (debug request to see how they behave)
def get_app_access_token(session):
    if KEY_FB_APP_TOKEN in session:
        return session[KEY_FB_APP_TOKEN]

    # Request app token if we weren't able to get if from session or filesystem
    fb_app_access_token_request = requests.get(settings.FB_APP_ACCESS_TOKEN_URL)
    fb_app_access_token_response = fb_app_access_token_request.json()
    print(str(fb_app_access_token_response))
    return fb_app_access_token_response


# Saves user id
# TODO Add user saving to login
def validate_auth_token(request, saved_token):
    # TODO save token in BD for current user

    app_access_token = saved_token
    if app_access_token is None:
        fb_app_access_token_response = get_app_access_token(request.session)

        if 'error' in fb_app_access_token_response:
            return False

        app_access_token = fb_app_access_token_response['access_token']
        request.session[KEY_FB_APP_TOKEN] = app_access_token

    # Validate current token
    fb_auth_token_debug_url = build_auth_token_debug_url(request.session[KEY_FB_AUTH_TOKEN], app_access_token)
    fb_auth_token_debug_response = requests.get(fb_auth_token_debug_url).json()

    response_data = fb_auth_token_debug_response['data']
    if not response_data['is_valid']:
        return False

    # Save user_id
    user_id = response_data['user_id']
    request.session[KEY_FB_USER_ID] = user_id

    user = authenticate(request, fb_id=user_id)
    if user is None:
        return False
    else:
        login(request, user)
        return True


#
# Date interval methods
#

# Using enum class create enumerations
class SummaryPeriod(enum.Enum):
    CurrentWeek = 1
    CurrentMonth = 2
    CurrentQuarter = 3
    LastWeek = 4
    LastTwoWeeks = 5
    LastMonth = 6
    LastQuarter = 7
    CurrentYear = 8


# TODO Check if is needed to adjust to timezone
def build_time_paging_param(summary_period):
    group_feed_time_paging = ''
    current_datetime = datetime.now()
    days_from_last_monday = current_datetime.weekday() if current_datetime.weekday() != 0 else 7
    last_monday = datetime.today() - timedelta(days=days_from_last_monday)

    if summary_period == SummaryPeriod.CurrentWeek:
        group_feed_time_paging = build_time_param_str(last_monday, current_datetime)
    elif summary_period == SummaryPeriod.LastWeek:
        second_to_last_monday = last_monday - timedelta(days=7)
        group_feed_time_paging = build_time_param_str(second_to_last_monday, last_monday)
    return group_feed_time_paging


def build_time_param_str(since_datetime, until_datetime):
    since_datetime = since_datetime.replace(hour=0, minute=0, second=0, microsecond=0)
    print(f'{since_datetime}\n{until_datetime}')
    return f'since={int(since_datetime.timestamp())}&until={int(until_datetime.timestamp())}'
