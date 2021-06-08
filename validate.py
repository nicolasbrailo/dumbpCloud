from flask import Flask, request, redirect
import os
import json
import random
import requests
import threading
import urllib.parse

class pCloudAuth(object):
    def __init__(self, client_id, client_secret, tok):
        self.client_id, self.client_secret, self.tok = client_id, client_secret, tok

    def get_auth_step1(self):
        return 'https://my.pcloud.com/oauth2/authorize?client_id={}&response_type=code'.\
                                format(self.client_id)

    def get_auth_step2(self, code):
        url = 'https://api.pcloud.com/oauth2_token?client_id={}&client_secret={}&code={}' \
                                .format(self.client_id, self.client_secret, code)
        r = requests.get(url)
        self.tok = r.json()['access_token']
        print("TOK IS " + self.tok)
        return self.tok

    def build_url(self, method, args):
        return 'https://api.pcloud.com/{}?access_token={}&{}'.format(method, self.tok,
                                                                 urllib.parse.urlencode(args))


class pCloudCli(object):
    def __init__(self, auth):
        self.auth = auth

    def get_checksum(self, cloud_path):
        r = requests.get(self.auth.build_url('checksumfile', {'path': cloud_path}))
        r = r.json()
        if 'error' in r and r['result'] == 2005:
            raise KeyError("No path {}".format(cloud_path))
        return r['md5']

    def recursive_ls(self, cloud_path, root_path=None):
        print(f"Reading cloud path {cloud_path}")

        if root_path is None:
            root_path = cloud_path

        r = requests.get(self.auth.build_url('listfolder', {'path': cloud_path}))
        if 'error' in r.json() and r.json()['result'] == 2005:
            raise KeyError("No remote directory {}".format(cloud_path))

        lst = []
        for cloud_file in r.json()['metadata']['contents']:
            if not cloud_file['isfolder']:
                fp = cloud_file['path'][len(root_path):]
                lst.append((fp, self.get_checksum(cloud_file['path'])))
            else:
                lst.extend(self.recursive_ls(cloud_file['path'], root_path))

        lst.sort()
        return lst


import hashlib
def md5(fname):
    hash_md5 = hashlib.md5()
    #sha1 = hashlib.sha1()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
            #sha1.update(chunk)
    return hash_md5.hexdigest()#, sha1.hexdigest()

def get_local(path):
    lst = []
    for dirpath, subdirs, files in os.walk(path):
        print(f"Reading local path {dirpath}")
        for fn in files:
            filepath = os.path.join(dirpath, fn)
            lst.append((filepath[len(path):], md5(filepath)))
    lst.sort()
    return lst

CLIENT_ID="PCLOUD_CLIENT_ID"
CLIENT_SECRET="PCLOUD_CLIENT_SECRETE"
CLIENT_TOK="PCLOUD_CLIENT_TOK"
LOCAL_PATH='/Volumes/NO NAME/Path/To/Dir'
CLOUD_PATH=                '/Path/To/Dir'

local_files = get_local(LOCAL_PATH)
cloud_files = pCloudCli(pCloudAuth(CLIENT_ID, CLIENT_SECRET, CLIENT_TOK)).recursive_ls(CLOUD_PATH)

print(local_files)
print('XXXXXXXXXXXXXXXXXXXX')
print(cloud_files)

local_filepaths = [fp for fp, fh in local_files]
cloud_filepaths = [fp for fp, fh in cloud_files]

seen_locally_missing_remote = []
seen_remote_missing_locally = []
wrong_hash = []

diff = set(local_files).symmetric_difference(set(cloud_files))
for fp,fhash in diff:
    if fp in local_filepaths and fp not in cloud_filepaths:
        seen_locally_missing_remote.append(fp)
    elif fp not in local_filepaths and fp in cloud_filepaths:
        seen_remote_missing_locally.append(fp)
    elif fp in local_filepaths and fp in cloud_filepaths:
        wrong_hash.append(fp)
    else:
        print(f"{fp} has a problem, but I don't know what")

print("Files present locally but missing in cloud:" + "\n\t".join(seen_locally_missing_remote))
print("XXXXXXXXXXX")
print("Files present remote but missing locally:" + "\n\t".join(seen_remote_missing_locally))
print("XXXXXXXXXXX")
print("Files with wrong hash" + "\n\t".join(wrong_hash))


