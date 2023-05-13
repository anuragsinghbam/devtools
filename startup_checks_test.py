#!/usr/bin/env python3
# Copyright (c) 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import sys
from unittest import mock
from unittest import TestCase

import pytest
import startup_checks as sc


class MockStorageClient():

  def get_bucket(self, bucket_name):
    return bucket_name


class MockInvalidStorageClient():

  def get_bucket(self, bucket_name):  # pylint: disable=W0613
    raise Exception()


class GoodMockVersionProvider:

  def retrieve(self, revision):  # pylint: disable=W0613
    return sc.CHROME_VERSION


class GoodVersionProviderCheck(sc.BaseVersionProviderReachableCheck):
  provider = GoodMockVersionProvider
  message = ""


class InvalidMockVersionProvider:

  def retrieve(self, revision):  # pylint: disable=W0613
    return "0123456789abcdef"


class InvalidVersionProviderCheck(sc.BaseVersionProviderReachableCheck):
  provider = InvalidMockVersionProvider
  message = ""


class UnexpectedMockVersionProvider:

  def retrieve(self, revision):  # pylint: disable=W0613
    raise Exception()


class UnexpectedVersionProviderCheck(sc.BaseVersionProviderReachableCheck):
  provider = UnexpectedMockVersionProvider
  message = ""


class LocalBucketChecksTest(TestCase):

  def setUp(self):
    self.monkeypatch = pytest.MonkeyPatch()

  def test_local_bucket(self):
    with self.monkeypatch.context() as m:
      m.setattr(sc, "LOCAL_BUCKET", "my-bucket")
      self.assertTrue(sc.LocalBucketCheck().is_fulfilled)


class ChromeSignedBucketPermissionCheckTest(TestCase):

  @mock.patch('startup_checks.storage.Client', side_effect=MockStorageClient)
  def test_storage_client(self, *mocks):  # pylint: disable=W0613
    self.assertTrue(sc.ChromeSignedBucketPermissionCheck().is_fulfilled)

  @mock.patch(
      'startup_checks.storage.Client', side_effect=MockInvalidStorageClient)
  def test_missing_permissions(self, *mocks):  # pylint: disable=W0613
    self.assertFalse(sc.ChromeSignedBucketPermissionCheck().is_fulfilled)


class BaseVersionProviderReachableTest(TestCase):

  def test_good(self):
    self.assertTrue(GoodVersionProviderCheck().is_fulfilled)

  def test_invalid(self):
    self.assertFalse(InvalidVersionProviderCheck().is_fulfilled)

  def test_unexpected(self):
    self.assertFalse(UnexpectedVersionProviderCheck().is_fulfilled)


if __name__ == "__main__":
  sys.exit(pytest.main([__file__]))
