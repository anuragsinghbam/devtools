#!/usr/bin/env python3
# Copyright (c) 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from abc import ABC, abstractmethod
from typing import Type

from config import CHROME_UNSIGNED_BUCKET
from config import LOCAL_BUCKET
from google.cloud import storage
from versions import BaseVersionProvider
from versions import ChromiumDashProvider
from versions import ChromiumRepositoryProvider

CHROME_VERSION = "94.0.4606.71"
CHROME_REVISION = "1d32b169326531e600d836bd395efc1b53d0f6ef"


class LocalBucketCheck:
  """Check for `LOCAL_BUCKET` environment."""
  message = ("No local storage bucket provided; set environment variable "
             "`LOCAL_BUCKET`")

  @property
  def is_fulfilled(self) -> bool:
    return bool(LOCAL_BUCKET)


class ChromeSignedBucketPermissionCheck:
  """Check access to the remote bucket.

  Access bucket information to validate that the READ permission is
  granted for the active GCP service account.
  """
  message = (
      f"No permissions to access remote bucket {CHROME_UNSIGNED_BUCKET}; check "
      "permissions")

  @property
  def is_fulfilled(self) -> bool:
    try:
      bucket = storage.Client().get_bucket(CHROME_UNSIGNED_BUCKET)
      return bool(bucket)
    except Exception:
      return False


class BaseVersionProviderReachableCheck(ABC):
  """Base implementation for checks using version providers.

  Send a request for a known CHROME_REVISION and verify that the
  response contains the expected CHROME_VERSION.
  """

  @property
  @abstractmethod
  def provider(self) -> Type[BaseVersionProvider]:
    pass

  @property
  @abstractmethod
  def message(self) -> str:
    pass

  @property
  def is_fulfilled(self) -> bool:
    try:
      version = self.provider().retrieve(CHROME_REVISION)
      return version == CHROME_VERSION
    except Exception:
      return False


class ChromiumDashReachableCheck(BaseVersionProviderReachableCheck):
  """Check availability of chromiumdash."""

  provider = ChromiumDashProvider
  message = "ChromiumDash cannot be reached."


class ChromiumRepositoryReachableCheck(BaseVersionProviderReachableCheck):
  """Check availability of the chromium repository."""

  provider = ChromiumRepositoryProvider
  message = "Chromium repository cannot be reached."


def run() -> None:
  checks = [
      LocalBucketCheck(),
      ChromeSignedBucketPermissionCheck(),
      ChromiumDashReachableCheck(),
      ChromiumRepositoryReachableCheck(),
  ]

  failed_checks = [c for c in checks if not c.is_fulfilled]
  error_lines = [
      f" * {c.__class__.__name__}: {c.message}" for c in failed_checks
  ]

  assert len(failed_checks) == 0, (
      f"{len(failed_checks)} startup check(s) failed:\n" +
      "\n".join(error_lines))
