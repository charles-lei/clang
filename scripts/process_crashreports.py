#!/usr/bin/env python
# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Looks for crash reports in tools/clang/crashreports and uploads them to GCS.
"""

import argparse
import datetime
import getpass
import glob
import os
import subprocess
import sys
import tarfile
import tempfile


GCS_BUCKET = 'chrome-clang-crash-reports'
THIS_DIR = os.path.dirname(__file__)
CRASHREPORTS_DIR = os.path.join(THIS_DIR, '..', 'crashreports')
GSUTIL = os.path.join(
    THIS_DIR, '..', '..', '..', 'third_party', 'depot_tools', 'gsutil.py')


def ProcessCrashreport(base, source):
  """Zip up all files belonging to a crash base name and upload them to GCS."""
  sys.stdout.write('Processing %s... ' % base)
  sys.stdout.flush()

  # Note that this will include the .sh and other files:
  files = glob.glob(os.path.join(CRASHREPORTS_DIR, base + '.*'))

  # Path design.
  # - For each crash, it should be easy to see which platform it was on,
  #   and which configuration it happened for.
  # - Crash prefixes should be regular so that a second bot could download
  #   crash reports and auto-triage them.
  # - Ideally the assert reason would be easily visible too, but clang doesn't
  #   write that to disk.
  # Prepend with '/v1' so that we can move to other schemes in the future if
  # needed.
  # /v1/yyyy-mm-dd/botname-basename.tgz
  now = datetime.datetime.now()
  dest = 'gs://%s/v1/%04d/%02d/%02d/%s-%s.tgz' % (
      GCS_BUCKET, now.year, now.month, now.day, source, base)

  # zipfile.ZipFile() defaults to Z_DEFAULT_COMPRESSION (6) and that can't
  # be overriden until Python 3.7. tarfile always uses compression level 9,
  # so use tarfile.
  tmp_name = None
  try:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.tgz') as tmp:
      tmp_name = tmp.name
      sys.stdout.write('compressing... ')
      sys.stdout.flush()
      with tarfile.open(mode='w:gz', fileobj=tmp) as tgz:
        for f in files:
          tgz.add(f, os.path.basename(f))
    sys.stdout.write('uploading... ')
    sys.stdout.flush()
    subprocess.check_call([sys.executable, GSUTIL, '-q', 'cp', tmp_name, dest])
    print 'done'
  finally:
    if tmp_name:
      os.remove(tmp_name)


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--source',  default='user-' + getpass.getuser(),
                      help='Source of the crash -- usually a bot name. '
                           'Leave empty to use your username.')
  args = parser.parse_args()
  # When clang notices that it crashes, it tries to write a .sh file containing
  # the command used to invoke clang, a source file containing the whole
  # input source code with an extension matching the input file (.c, .cpp, ...),
  # and potentially other temp files and directories.
  # If generating the unified input source file fails, the .sh file won't
  # be written. (see Driver::generateCompilationDiagnostics()).
  # As a heuristic, find all .sh files in the crashreports directory, then
  # zip each up along with all other files that have the same basename with
  # different extensions.
  for reproducer in glob.glob(os.path.join(CRASHREPORTS_DIR, '*.sh')):
    base = os.path.splitext(os.path.basename(reproducer))[0]
    ProcessCrashreport(base, args.source)


if __name__ == '__main__':
  try:
    main()
  except Exception as e:
    print 'got exception:', e
