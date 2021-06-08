# dumbpCloud
A dumb pCloud client to manually sync a single directory without needing to run a full server

# Running
Run as 'python3 ./sync.py syncdir'

In the first run, dumbpCloud will request configuration details about your pCloud oAuth information. Subsequent runs will use a local settings file.

dumbpCloud will sync a local directory to a pCloud directory with the same name. It will download those files which have a newer modification date in the cloud storage, and it will upload those local files which are newer than the cloud stored files. There is no clever conflict solving, or even support for deleted files: all that is up to the user.


# Validation

The validate script will check if a local copy is 100% the same as a cloud copy. Change the script by adding the right client id, secret and token, then run on a path to get the report of missing files.

