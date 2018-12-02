import sys
import os
import requests
import shelve
import urllib
from pathlib import Path
from email.utils import parsedate_tz, mktime_tz
import datetime
import random
import shutil
import tempfile

def init_oauth_setup(settings):
    """ Ensure dictionary settings has oauth data """
    if ('OAUTH_CLIENT_ID' in settings) and ('OAUTH_CLIENT_SECRET' in settings):
        pass    # All good
    else:
        print("OAuth config missing. Setting up OAuth.")
        print("Goto https://docs.pcloud.com/my_apps/ and look for oauth client/secret.")
        print("What's the Client Id?")
        settings['OAUTH_CLIENT_ID'] = sys.stdin.readline().strip()
        print("What's the Client secret?")
        settings['OAUTH_CLIENT_SECRET'] = sys.stdin.readline().strip()


def get_pcloud_oauth_tok(oauth_client_id, oauth_client_secret):
    """ Returns a pcloud oauth token by (hackishly) requesting user input """
    API_AUTH_GETCODE = 'https://my.pcloud.com/oauth2/authorize?client_id={}&response_type=code'.format(oauth_client_id)
    API_AUTH_TOK = 'https://api.pcloud.com/oauth2_token?client_id={}&client_secret={}' \
                        .format(oauth_client_id, oauth_client_secret) + '&code={}'

    print("Goto {} and paste de token here: ".format(API_AUTH_GETCODE))
    pcloud_code = sys.stdin.readline()

    r = requests.get(API_AUTH_TOK.format(pcloud_code))
    return r.json()['access_token']


def is_logged_in(oauth_tok):
    """ True if oauth_tok is a valid token which can be used for API calls, False otherwise """
    try:
        r = requests.get('https://api.pcloud.com/userinfo?access_token={}'.format(oauth_tok))
        return r.json()['email'] is not None
    except:
        return False

def build_settings(settings_file):
    """ Open a settings file and ensures all required settings are there """
    settings = shelve.open(settings_file)
    init_oauth_setup(settings)

    if ('OAUTH_TOK' not in settings) or not is_logged_in(settings['OAUTH_TOK']):
        settings['OAUTH_TOK'] = get_pcloud_oauth_tok(settings['OAUTH_CLIENT_ID'], settings['OAUTH_CLIENT_SECRET'])

    return settings

class pCloudApi(object):
    def __init__(self, settings):
        self.settings = settings

    def build_url(self, method, args):
        return 'https://api.pcloud.com/{}?access_token={}&{}'.format(method,
                                                                     self.settings['OAUTH_TOK'],
                                                                     urllib.parse.urlencode(args))

    def downloadfile(self, cloudpath, localpath):
        # Get a download link
        r = requests.get(api.build_url('getfilelink', {'path': cloudpath})).json()
        url = 'https://' + random.choice(r['hosts']) + r['path']

        # Download actual file
        r = requests.get(url, stream=True)
        if not r.status_code == 200:
            raise Exception("Can't download {}".format(cloudpath))

        # Copy downloaded file to a tmp location
        tmpfp = tempfile.NamedTemporaryFile(delete=False)
        r.raw.decode_content = True
        shutil.copyfileobj(r.raw, tmpfp)  

        # Replace local file with downloaded file
        try:
            os.makedirs(os.path.dirname(localpath))
        except FileExistsError:
            pass

        shutil.move(tmpfp.name, localpath)

    def makedirs(self, path):
        currpath = ''
        for subdir in [x for x in path.split('/') if len(x) > 0]:
            currpath += '/' + subdir
            r = requests.get(api.build_url('createfolder', {'path': currpath,
                                                            'name': ''}))

    def uploadfile(self, localpath, cloudpath):
        url = api.build_url('uploadfile', {'path': os.path.dirname(cloudpath),
                                           'filename': os.path.basename(cloudpath),
                                           'nopartial': '1'})
        files = {'file': open(localpath, 'rb')}
        r = requests.post(url, files=files)

        if 'error' in r.json() and r.json()['result'] == 2005:
            # Path doesn't exist: create it and retry
            self.makedirs(os.path.dirname(cloudpath))
            return requests.post(url, files=files).json()

        return r.json()

    def recursive_ls(self, path):
        r = requests.get(api.build_url('listfolder', {'path': path}))
        if 'error' in r.json() and r.json()['result'] == 2005:
            # Sync dir doesn't exist (yet)
            return []

        lst = []
        for cloud_file in r.json()['metadata']['contents']:
            if not cloud_file['isfolder']:
                lst.append((cloud_file['path'], api.pcloud_date_to_timestamp(cloud_file['modified'])))
            else:
                lst.extend(self.recursive_ls(cloud_file['path']))

        return lst

    def pcloud_date_to_timestamp(self, date_in_rfc2822):
        return mktime_tz(parsedate_tz(date_in_rfc2822))

    def get_modified_date(self, path):
        r = requests.get(api.build_url('checksumfile', {'path': path}))
        if 'error' in r.json():
            return 0 # File doesn't exist, say it's the oldest it can be
        return self.pcloud_date_to_timestamp(r.json()['metadata']['modified'])


class LocalFileList(object):
    def __init__(self, sync_path):
        self.sync_path = sync_path
        self.sync_name = os.path.basename(os.path.dirname(sync_path))

    def get_sync_name(self):
        return self.sync_name

    def recursive_ls(self, path):
        """ Get a list of files to sync and their target destination """
        return [(str(x), self.get_modified_date(str(x))) 
                        for x in list(Path(path).rglob('*'))
                        if x.is_file()]

    def get_modified_date(self, path_to_file):
        return os.stat(path_to_file).st_mtime

    def cloud_name_for(self, local_path):
        skip_prefix_len = len(os.path.commonprefix([self.sync_path, local_path]))
        sync_dest = '/' + self.sync_name + '/' + local_path[skip_prefix_len:]
        return sync_dest

    def local_name_for(self, cloud_path):
        prefix = '/' + self.sync_name + '/'
        if not cloud_path.startswith(prefix):
            raise Exception("Can't deduce local name for cloud file {}".format(cloud_path))

        sep = '/'
        if self.sync_path[-1:] == '/':
            sep = ''

        return self.sync_path + sep + cloud_path[len(prefix):]


class PCloudSync(object):
    def __init__(self, local, api):
        self.local = local
        self.api = api
        # Don't fail if sync dir doesn't exist: it'll be automagically created
        #r = requests.get(api.build_url('listfolder', {'path': '/' + local.get_sync_name()}))
        #if 'error' in r.json():
        #    raise Exception("Sync directory {} doesn't exist".format(local.get_sync_name()))

    def files_to_sync(self):
        """ Create a list of (localfile, local_timestamp, remotefile, remote_timestamp, action) """

        actions = {}

        # Start assuming all local files need to be uploaded
        for fn in self.local.recursive_ls(self.local.sync_path):
            actions[fn[0]] = (fn[0], fn[1], self.local.cloud_name_for(fn[0]), 0, 'upload')

        # Update actions map: download newer cloud files, upload newer local files
        for fn in self.api.recursive_ls('/' + self.local.get_sync_name()):
            localname = self.local.local_name_for(fn[0])
            if localname not in actions:
                actions[localname] = (localname, 0, fn[0], fn[1], 'download')
            elif actions[localname][1] < fn[1]: # cloud is newer
                localtime = actions[localname][1]
                actions[localname] = (localname, localtime, fn[0], fn[1], 'download')
            else:
                localtime = actions[localname][1]
                actions[localname] = (localname, localtime, fn[0], fn[1], 'upload')

        return actions.values()

    def do_sync(self, istestrun):
        for localpath,_,cloudpath,_,action in self.files_to_sync():
            if action == 'download':
                print("Download {} to {}".format(cloudpath, localpath))
                if not istestrun:
                    self.api.downloadfile(cloudpath, localpath)
            elif action == 'upload':
                print("Upload {} to {}".format(localpath, cloudpath))
                if not istestrun:
                    self.api.uploadfile(localpath, cloudpath)
            else:
                raise Exception("End of world exception")


import argparse

parser = argparse.ArgumentParser(description='Sync to pCloud')
parser.add_argument('local_path', metavar='local_path', type=str,
                    help='Path to local set of files')
parser.add_argument('--testrun', dest='istestrun', action='store_true',
                    default=False, help='Only print actions list')
parser.add_argument('--settings_file', dest='settings_file',
                    default='nico_pcloud_sync.config',
                    help='Local settings cache to store (eg) oauth data')

args = parser.parse_args()
if not os.path.exists(args.local_path):
    print("Can't access {}".format(args.local_path))
    exit(1)

api = pCloudApi(build_settings(args.settings_file))
file_list = LocalFileList(args.local_path)
sync = PCloudSync(file_list, api)
if args.istestrun:
    print("Test run: no changes will be applied!")
sync.do_sync(args.istestrun)

