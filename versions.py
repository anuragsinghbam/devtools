#!/usr/bin/env python3
# Copyright (c) 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from abc import ABC
import base64
import binascii
import logging
import re
from typing import cast, Dict, List, Optional

from config import LOCAL_BUCKET
from google.cloud import storage
from pipelines import BaseProvider
from pipelines import CONTINUE_SEARCH
from pipelines import DOES_NOT_EXIST
from pipelines import Pipeline
import requests
from storage_helper import download_blob
from storage_helper import upload_from_string

CHROMIUM_DASH_URL = "https://chromiumdash.appspot.com/fetch_commit?commit="
REPOSITORY_URL = (
    "https://chromium.googlesource.com/chromium/src/+/%s/chrome/VERSION"
    "?format=TEXT")

VERSION_PATTERN = re.compile(r"^[1-9]\d*\.\d*\.[1-9]\d*\.\d*$")
VERSION_FILE_PATTERN = re.compile(
    r"^MAJOR=(?P<major>\d+)\nMINOR=(?P<minor>\d+)\nBUILD=(?P<build>\d+)\n"
    r"PATCH=(?P<patch>\d+)\n$")


def is_valid_version(version) -> bool:
  """Validate that a version matches <major.minor.build.patch>."""
  if VERSION_PATTERN.match(version) is None:
    return False

  # Validate no leading zeros
  major, minor, build, patch = [int(part) for part in version.split(".")]
  return version == f"{major}.{minor}.{build}.{patch}"


def is_valid_revision(revision, length=40):
  """Validate revision consists of hexadecimal characters with a given length.

  First Chromium versions have used 6-digit hashes, while more recent
  revisions use 40-digit hashes.
  """
  return re.match(r"^[0-9a-f]{%s}$" % length, revision) is not None


class BaseVersionProvider(BaseProvider[str, str], ABC):
  """Version providers expect a str parameter (the revision), and return a str
  content (the version)."""


class LocalMemoryProvider(BaseVersionProvider):
  """Retrieve chrome version from local memory.

  This cache is only valid for the lifetime of the app runtime.
  """

  def __init__(self):
    self.version_by_revision: Dict[str, str] = dict()

  def retrieve(self, revision):
    return (self.version_by_revision.get(revision, CONTINUE_SEARCH) or
            DOES_NOT_EXIST)

  def process_response(self, provider, revision, version):
    # Do not cache responses from the provider itself
    if provider == self:
      return

    # Cache response
    # NOTE: We might want to expire a cached None response in case the revision
    #       will become part of a version. For now, we assume that the process
    #       lifetime will be sufficiently short.
    self.version_by_revision[revision] = version


class LocalBucketProvider(BaseVersionProvider):
  """Retrieve chrome version from the local bucket."""

  def __init__(self):
    self.bucket = storage.Client().get_bucket(LOCAL_BUCKET)

  def _get_bucket_path(self, revision):
    return f"version_by_revision/{revision}"

  def retrieve(self, revision):
    blob = download_blob(self.bucket, self._get_bucket_path(revision))

    if blob is None:
      return CONTINUE_SEARCH

    return blob.decode("utf-8")

  def process_response(self, provider, revision, version):
    # Do not cache responses from the provider itself or None
    if provider == self or version is None:
      return

    blob = self.bucket.blob(self._get_bucket_path(revision))
    upload_from_string(blob, version)


class ChromiumDashProvider(BaseVersionProvider):
  """Retrieve chrome version from chromiumdash (part of infra_internal)."""

  def retrieve(self, revision):
    try:
      response = requests.get(CHROMIUM_DASH_URL + revision).json()
    except Exception as e:
      logging.error('Invalid chromiumdash response %s', e)
      return CONTINUE_SEARCH

    if "error" in response:
      if response["error"] == "Commit not found.":
        logging.info('Revision %s is not included in a version (yet)', revision)
        return CONTINUE_SEARCH

      logging.error('Revision %s raised unexpected behaviour with chromiumdash',
                    revision)
      return CONTINUE_SEARCH

    version = response.get("earliest")
    if version is None:
      logging.warning("Revision %s does not have a version within chromiumdash",
                      revision)
      return CONTINUE_SEARCH

    if not is_valid_version(version):
      logging.error("Invalid version %s received from chromiumdash", version)
      return CONTINUE_SEARCH

    return cast(str, version)


class ChromiumRepositoryProvider(BaseVersionProvider):
  """Retrieve chromium version from the official repository.

  While we aim to retrieve the first version where a revision is included, the
  VERSION file for a specific revision returns the most recent version before
  and including this revision. E.g.

  03:14:41 → ee5e6b… → version push to 97.0.4692.0
  03:18:42 → f43c8b… → some patch
  04:52:41 → 57aabc… → version push to 97.0.4692.1

  This method returns the previous version 97.0.4692.0 for revision f43c8b…
  instead of 97.0.4692.1. However, only releases are installable and they always
  refer to the correct revisions (ee5e6b… and 57aabc…).
  """

  TIMEOUT = 10

  def retrieve(self, revision):
    url = REPOSITORY_URL % revision
    try:
      response = requests.get(url, timeout=self.TIMEOUT)
      if response.status_code == 404:
        logging.info('Revision %s not found in chromium repository', revision)
        return DOES_NOT_EXIST
    except requests.exceptions.ReadTimeout:
      logging.warning(
          '%ss timeout reached for revision %s in chromium repository',
          self.TIMEOUT, revision)
      return CONTINUE_SEARCH

    # Parse version
    try:
      content = base64.b64decode(response.content).decode("utf-8")
    except binascii.Error:
      logging.error('VERSION file for revision %s is not base64 encoded',
                    revision)
      return CONTINUE_SEARCH

    match = VERSION_FILE_PATTERN.match(content)
    if not match:
      logging.error('Cannot parse VERSION file for revision %s, found %s',
                    revision, content)
      return CONTINUE_SEARCH

    version_parts = match.groupdict()
    return ".".join([
        version_parts["major"], version_parts["minor"], version_parts["build"],
        version_parts["patch"]
    ])


# The order is important since the next provider will only be requested if the
# current provider cannot find a matching version. Providers at the top are less
# complete but have a lower latency. We use a lazy init approach to avoid call-
# outs when starting the app.

_PIPELINE = None


def get_pipeline() -> Pipeline[str, str]:
  global _PIPELINE
  if _PIPELINE is None:
    _PIPELINE = Pipeline[str, str]([
        LocalMemoryProvider(),
        LocalBucketProvider(),
        ChromiumDashProvider(),
        ChromiumRepositoryProvider(),
    ])
  return _PIPELINE


def get_version_from_revision(revision: str) -> Optional[str]:
  """Return the earliest chrome version inlcuding the revision.

  Args:
    revision (str): 40 character chromium revision

  Returns:
    Optional[str]: Version or None if commit is invalid or not included in a
                   version
  """
  if not is_valid_revision(revision):
    logging.info('Invalid revision format %s', revision)
    return None

  version = get_pipeline().retrieve(revision)
  if not version:
    logging.info(
        "Trying to resolve revison %s, but no version can be determined",
        revision)

  return version
